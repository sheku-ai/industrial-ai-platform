"""Durable filesystem storage provider implementation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.storage_provider_contracts import (
    STORAGE_OPERATION_CREATE,
    STORAGE_OPERATION_DELETE,
    STORAGE_OPERATION_DOWNLOAD,
    STORAGE_OPERATION_GENERATE_DOWNLOAD,
    STORAGE_OPERATION_GENERATE_UPLOAD,
    STORAGE_OPERATION_GET,
    STORAGE_OPERATION_HEAD,
    STORAGE_OPERATION_UPLOAD,
    STORAGE_PROVIDER_STATUS_CONFIGURED,
    StorageObjectHandle,
    StorageOperationRequest,
    StorageOperationResult,
    StorageProvider,
    StorageProviderDescriptor,
    build_storage_not_configured_result,
    build_storage_provider_capability,
    build_storage_provider_descriptor,
    safe_storage_configuration_fingerprint,
    sanitize_storage_provider_configuration,
)

FILESYSTEM_STORAGE_PROVIDER_NAME = "filesystem"
FILESYSTEM_STORAGE_PROVIDER_TYPE = "filesystem"
FILESYSTEM_METADATA_SUFFIX = ".metadata.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _checksum(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _empty_checksum() -> str:
    return _checksum(b"")


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _filesystem_capabilities() -> tuple:
    return tuple(
        build_storage_provider_capability(
            operation=operation,
            supported=True,
            configured=True,
            status=STORAGE_PROVIDER_STATUS_CONFIGURED,
        )
        for operation in (
            STORAGE_OPERATION_CREATE,
            STORAGE_OPERATION_UPLOAD,
            STORAGE_OPERATION_HEAD,
            STORAGE_OPERATION_DOWNLOAD,
            STORAGE_OPERATION_DELETE,
            STORAGE_OPERATION_GET,
            STORAGE_OPERATION_GENERATE_UPLOAD,
            STORAGE_OPERATION_GENERATE_DOWNLOAD,
        )
    )


def _root_from_configuration(configuration: dict[str, Any] | None = None) -> Path:
    config = dict(configuration or {})
    raw_root = (
        config.get("storage_root")
        or config.get("root_path")
        or config.get("filesystem_root")
        or get_settings().filesystem_storage_root
    )
    return Path(str(raw_root)).expanduser().resolve()


def _object_id_from_descriptor(request: StorageOperationRequest) -> str:
    supplied = (
        request.descriptor.get("object_key")
        or request.descriptor.get("storage_key")
        or request.metadata.get("object_key")
        or request.metadata.get("storage_key")
    )
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()
    artifact_id = request.descriptor.get("artifact_id") or request.metadata.get("artifact_id")
    upload_session_id = request.descriptor.get("upload_session_id") or request.metadata.get("upload_session_id")
    seed = _stable_json(
        {
            "artifact_id": artifact_id,
            "upload_session_id": upload_session_id,
            "content_type": request.descriptor.get("content_type") or request.descriptor.get("mime_type"),
            "file_name": request.descriptor.get("file_name"),
        }
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{artifact_id or 'artifact-unknown'}-{digest[:24]}"


class FilesystemStorageProvider(StorageProvider):
    provider_name = FILESYSTEM_STORAGE_PROVIDER_NAME
    provider_type = FILESYSTEM_STORAGE_PROVIDER_TYPE
    configured = True

    def __init__(self, configuration: dict[str, Any] | None = None) -> None:
        self.configuration = dict(configuration or {})
        self.root_path = _root_from_configuration(self.configuration)
        self.root_path.mkdir(parents=True, exist_ok=True)
        safe_configuration = sanitize_storage_provider_configuration(
            {
                **self.configuration,
                "provider_name": FILESYSTEM_STORAGE_PROVIDER_NAME,
                "provider_type": FILESYSTEM_STORAGE_PROVIDER_TYPE,
                "storage_root": str(self.root_path),
            }
        )
        self._descriptor = build_storage_provider_descriptor(
            provider_name=FILESYSTEM_STORAGE_PROVIDER_NAME,
            provider_type=FILESYSTEM_STORAGE_PROVIDER_TYPE,
            configured=True,
            status=STORAGE_PROVIDER_STATUS_CONFIGURED,
            capabilities=_filesystem_capabilities(),
            safe_configuration_fingerprint=safe_storage_configuration_fingerprint(safe_configuration),
            metadata={
                "storage_scope": "local_filesystem",
                "persistent": True,
                "durable": True,
                "real_storage_operations_enabled": True,
                "provider_reference": "filesystem_reference_provider",
                "storage_root": str(self.root_path),
                "safe_configuration": safe_configuration,
            },
        )

    @property
    def descriptor(self) -> StorageProviderDescriptor:
        return self._descriptor

    def _blocked_result(
        self, request: StorageOperationRequest, *, status: str, next_step: str
    ) -> StorageOperationResult:
        result = build_storage_not_configured_result(request)
        return StorageOperationResult(
            operation=request.operation,
            status=status,
            provider=self.descriptor,
            executed=False,
            storage_ready=False,
            object_handle=None,
            metadata={
                **result.metadata,
                "real_storage_operations_enabled": True,
                "provider_type": FILESYSTEM_STORAGE_PROVIDER_TYPE,
            },
            required_next_step=next_step,
        )

    def _handle_reference(self, object_handle: StorageObjectHandle | None) -> dict[str, Any]:
        if object_handle is None:
            return {}
        return dict(object_handle.reference or {})

    def _handle_key(self, object_handle: StorageObjectHandle | None) -> str | None:
        reference = self._handle_reference(object_handle)
        value = reference.get("object_handle") or reference.get("object_key") or reference.get("id")
        return str(value) if value else None

    def _safe_object_path(self, object_key: str) -> Path:
        normalized = object_key.replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or "\x00" in normalized:
            raise ValueError("invalid filesystem storage object key")
        parts = [part for part in normalized.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("invalid filesystem storage object key")
        path = (self.root_path / Path(*parts)).resolve()
        try:
            path.relative_to(self.root_path)
        except ValueError as exc:
            raise ValueError("filesystem storage object key escapes storage root") from exc
        return path

    def _metadata_path(self, object_path: Path) -> Path:
        return object_path.with_name(f"{object_path.name}{FILESYSTEM_METADATA_SUFFIX}")

    def _load_record(self, object_key: str) -> dict[str, Any] | None:
        try:
            object_path = self._safe_object_path(object_key)
        except ValueError:
            return None
        metadata_path = self._metadata_path(object_path)
        if not metadata_path.exists():
            return None
        try:
            record = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        record["object_path"] = str(object_path)
        record["metadata_path"] = str(metadata_path)
        return record

    def _write_record(self, object_path: Path, record: dict[str, Any]) -> None:
        metadata_path = self._metadata_path(object_path)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        persisted = {
            key: value for key, value in record.items() if key not in {"content", "object_path", "metadata_path"}
        }
        metadata_path.write_text(json.dumps(persisted, sort_keys=True, indent=2, default=str), encoding="utf-8")

    def _object_handle(self, object_key: str) -> StorageObjectHandle:
        return StorageObjectHandle(
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            reference={
                "object_handle": object_key,
                "object_key": object_key,
                "storage_root": str(self.root_path),
            },
        )

    def _record_for_request(self, request: StorageOperationRequest) -> tuple[str | None, dict[str, Any] | None]:
        object_key = self._handle_key(request.object_handle)
        if not object_key:
            return None, None
        return object_key, self._load_record(object_key)

    def _refresh_record_from_disk(self, record: dict[str, Any]) -> dict[str, Any]:
        object_path = Path(str(record.get("object_path") or ""))
        object_exists = object_path.exists() and not bool(record.get("deleted"))
        content = object_path.read_bytes() if object_exists else b""
        record["size_bytes"] = len(content) if object_exists else int(record.get("size_bytes") or 0)
        record["checksum"] = _checksum(content) if object_exists else record.get("checksum")
        record["uploaded"] = object_exists and bool(record.get("uploaded"))
        return record

    def _object_result(
        self,
        request: StorageOperationRequest,
        *,
        status: str,
        record: dict[str, Any],
        include_content: bool = False,
        required_next_step: str | None = None,
    ) -> StorageOperationResult:
        record = self._refresh_record_from_disk(record)
        object_handle = record.get("object_handle") if isinstance(record.get("object_handle"), dict) else None
        object_exists = (
            not bool(record.get("deleted"))
            and bool(record.get("object_path"))
            and Path(str(record.get("object_path"))).exists()
        )
        content = Path(str(record.get("object_path"))).read_bytes() if include_content and object_exists else b""
        metadata = {
            "object_handle": object_handle,
            "object_exists": object_exists,
            "object_stored": object_exists and bool(record.get("uploaded")),
            "file_uploaded": object_exists and bool(record.get("uploaded")),
            "checksum_calculated": object_exists and bool(record.get("checksum")),
            "checksum": record.get("checksum"),
            "content_length": record.get("size_bytes", 0),
            "content_type": record.get("content_type"),
            "metadata": dict(record.get("metadata") or {}),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "deleted": bool(record.get("deleted")),
            "storage_root": str(self.root_path),
            "storage_key": record.get("object_key"),
            "real_storage_operations_enabled": True,
            "operation_request": request.as_dict(),
        }
        if include_content:
            metadata["content"] = content
        return StorageOperationResult(
            operation=request.operation,
            status=status,
            provider=self.descriptor,
            executed=True,
            storage_ready=object_exists,
            object_handle=StorageObjectHandle(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                reference=dict((object_handle or {}).get("reference") or object_handle or {}),
            )
            if object_handle
            else None,
            metadata=metadata,
            required_next_step=required_next_step,
        )

    def latest_object_for_artifact(
        self, artifact_id: str | None, *, include_deleted: bool = False
    ) -> dict[str, Any] | None:
        if not artifact_id:
            return None
        matches: list[dict[str, Any]] = []
        for metadata_path in self.root_path.rglob(f"*{FILESYSTEM_METADATA_SUFFIX}"):
            try:
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            descriptor = (record.get("metadata") or {}).get("descriptor") or {}
            if str(descriptor.get("artifact_id")) != str(artifact_id):
                continue
            if not include_deleted and record.get("deleted"):
                continue
            object_key = str(record.get("object_key") or "")
            try:
                object_path = self._safe_object_path(object_key)
            except ValueError:
                continue
            record["object_path"] = str(object_path)
            record["metadata_path"] = str(metadata_path)
            matches.append(record)
        if not matches:
            return None
        return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]

    def create_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        try:
            object_key = _object_id_from_descriptor(request)
            object_path = self._safe_object_path(object_key)
        except ValueError as exc:
            return self._blocked_result(request, status="invalid_object_key", next_step=str(exc))
        existing_record = self._load_record(object_key)
        if existing_record is not None and not existing_record.get("deleted"):
            return self._object_result(
                request,
                status="object_created",
                record=existing_record,
                required_next_step="upload_object" if not existing_record.get("uploaded") else "head_object",
            )
        now = _utc_now()
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            object_path.write_bytes(b"")
        content_type = request.descriptor.get("content_type") or request.descriptor.get("mime_type")
        object_handle = self._object_handle(object_key)
        record = {
            "object_key": object_key,
            "object_handle": object_handle.as_dict(),
            "metadata": {
                **dict(request.metadata or {}),
                "descriptor": dict(request.descriptor or {}),
                "requested_by": request.requested_by,
            },
            "content_type": content_type,
            "size_bytes": 0,
            "checksum": _empty_checksum(),
            "created_at": now,
            "updated_at": now,
            "deleted": False,
            "uploaded": False,
        }
        self._write_record(object_path, record)
        return StorageOperationResult(
            operation=STORAGE_OPERATION_CREATE,
            status="object_created",
            provider=self.descriptor,
            executed=True,
            storage_ready=True,
            object_handle=object_handle,
            metadata={
                "object_created": True,
                "object_exists": True,
                "object_stored": False,
                "file_uploaded": False,
                "checksum_calculated": False,
                "storage_root": str(self.root_path),
                "storage_key": object_key,
                "real_storage_operations_enabled": True,
                "record": record,
                "operation_request": request.as_dict(),
            },
            required_next_step="upload_object",
        )

    def upload_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_key, record = self._record_for_request(request)
        if not object_key:
            return self._blocked_result(request, status="object_handle_required", next_step="provide_object_handle")
        if record is None or record.get("deleted"):
            return self._blocked_result(request, status="object_not_found", next_step="create_object")
        content = request.payload if isinstance(request.payload, bytes) else b""
        now = _utc_now()
        object_path = self._safe_object_path(object_key)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(content)
        content_type = (
            request.descriptor.get("content_type") or request.descriptor.get("mime_type") or record.get("content_type")
        )
        sanitized_descriptor = {
            key: value
            for key, value in dict(request.descriptor or {}).items()
            if key not in {"content", "content_bytes", "content_text"}
        }
        record.update(
            {
                "object_path": str(object_path),
                "metadata": {
                    **dict(record.get("metadata") or {}),
                    **dict(request.metadata or {}),
                    "descriptor": {
                        **dict((record.get("metadata") or {}).get("descriptor") or {}),
                        **sanitized_descriptor,
                    },
                    "requested_by": request.requested_by,
                },
                "content_type": content_type,
                "size_bytes": len(content),
                "checksum": _checksum(content),
                "updated_at": now,
                "deleted": False,
                "uploaded": True,
            }
        )
        self._write_record(object_path, record)
        return self._object_result(
            request,
            status="object_uploaded",
            record=record,
            required_next_step="head_object",
        )

    def delete_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_key, record = self._record_for_request(request)
        if not object_key:
            return self._blocked_result(request, status="object_handle_required", next_step="provide_object_handle")
        if record is None:
            now = _utc_now()
            object_path = self._safe_object_path(object_key)
            record = {
                "object_key": object_key,
                "object_handle": self._object_handle(object_key).as_dict(),
                "metadata": {"requested_by": request.requested_by},
                "content_type": None,
                "size_bytes": 0,
                "checksum": None,
                "created_at": now,
                "updated_at": now,
                "deleted": True,
                "uploaded": False,
                "object_path": str(object_path),
            }
        object_path = self._safe_object_path(object_key)
        metadata_path = self._metadata_path(object_path)
        if object_path.exists():
            object_path.unlink()
        record["deleted"] = True
        record["updated_at"] = _utc_now()
        record["object_path"] = str(object_path)
        if metadata_path.exists() or record:
            self._write_record(object_path, record)
        return self._object_result(
            request,
            status="object_deleted",
            record=record,
            required_next_step="create_object",
        )

    def get_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_key, record = self._record_for_request(request)
        if not object_key:
            return self._blocked_result(request, status="object_handle_required", next_step="provide_object_handle")
        if record is None or record.get("deleted"):
            return self._blocked_result(request, status="object_not_found", next_step="create_object")
        return self._object_result(
            request,
            status="object_downloaded",
            record=record,
            include_content=True,
        )

    def head_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_key, record = self._record_for_request(request)
        if not object_key:
            return self._blocked_result(request, status="object_handle_required", next_step="provide_object_handle")
        if record is None or record.get("deleted"):
            return self._blocked_result(request, status="object_not_found", next_step="create_object")
        return self._object_result(
            request,
            status="object_head",
            record=record,
        )

    def generate_download(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._blocked_result(request, status="generate_download_not_implemented", next_step="use_get_object")

    def generate_upload(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._blocked_result(request, status="generate_upload_not_implemented", next_step="use_create_object")
