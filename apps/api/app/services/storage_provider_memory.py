"""In-memory storage provider implementation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

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
)

MEMORY_STORAGE_PROVIDER_NAME = "memory"
MEMORY_STORAGE_PROVIDER_TYPE = "memory"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _empty_checksum() -> str:
    return f"sha256:{hashlib.sha256(b'').hexdigest()}"


def _checksum(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _memory_capabilities() -> tuple:
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


class InMemoryStorageProvider(StorageProvider):
    provider_name = MEMORY_STORAGE_PROVIDER_NAME
    provider_type = MEMORY_STORAGE_PROVIDER_TYPE
    configured = True

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self._descriptor = build_storage_provider_descriptor(
            provider_name=MEMORY_STORAGE_PROVIDER_NAME,
            provider_type=MEMORY_STORAGE_PROVIDER_TYPE,
            configured=True,
            status=STORAGE_PROVIDER_STATUS_CONFIGURED,
            capabilities=_memory_capabilities(),
            metadata={
                "storage_scope": "process_memory",
                "persistent": False,
                "real_storage_operations_enabled": True,
                "provider_reference": "in_memory_reference_provider",
            },
        )

    @property
    def descriptor(self) -> StorageProviderDescriptor:
        return self._descriptor

    def _handle_key(self, object_handle: StorageObjectHandle | None) -> str | None:
        if object_handle is None:
            return None
        reference = object_handle.reference or {}
        value = reference.get("object_handle") or reference.get("id")
        return str(value) if value else None

    def latest_object_for_artifact(
        self, artifact_id: str | None, *, include_deleted: bool = False
    ) -> dict[str, Any] | None:
        if not artifact_id:
            return None
        matches = []
        for record in self.objects.values():
            descriptor = (record.get("metadata") or {}).get("descriptor") or {}
            if str(descriptor.get("artifact_id")) == str(artifact_id) and (
                include_deleted or not record.get("deleted")
            ):
                matches.append(record)
        if not matches:
            return None
        return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]

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
                "provider_type": MEMORY_STORAGE_PROVIDER_TYPE,
            },
            required_next_step=next_step,
        )

    def _object_result(
        self,
        request: StorageOperationRequest,
        *,
        status: str,
        record: dict[str, Any],
        include_content: bool = False,
        required_next_step: str | None = None,
    ) -> StorageOperationResult:
        object_handle = record.get("object_handle") if isinstance(record.get("object_handle"), dict) else None
        content = record.get("content") if isinstance(record.get("content"), bytes) else b""
        object_exists = not bool(record.get("deleted"))
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

    def _record_for_request(self, request: StorageOperationRequest) -> tuple[str | None, dict[str, Any] | None]:
        object_key = self._handle_key(request.object_handle)
        if not object_key:
            return None, None
        return object_key, self.objects.get(object_key)

    def create_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_id = str(uuid.uuid4())
        now = _utc_now()
        object_handle = StorageObjectHandle(
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            reference={"object_handle": object_id},
        )
        content_type = request.descriptor.get("content_type") or request.descriptor.get("mime_type")
        record = {
            "object_handle": object_handle.as_dict(),
            "content": b"",
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
        self.objects[object_id] = record
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
                "real_storage_operations_enabled": True,
                "record": {
                    **record,
                    "content": None,
                },
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
        content_type = (
            request.descriptor.get("content_type") or request.descriptor.get("mime_type") or record.get("content_type")
        )
        sanitized_descriptor = {
            key: value
            for key, value in dict(request.descriptor or {}).items()
            if key not in {"content", "content_bytes", "content_text"}
        }
        record["content"] = content
        record["metadata"] = {
            **dict(record.get("metadata") or {}),
            **dict(request.metadata or {}),
            "descriptor": {
                **dict((record.get("metadata") or {}).get("descriptor") or {}),
                **sanitized_descriptor,
            },
            "requested_by": request.requested_by,
        }
        record["content_type"] = content_type
        record["size_bytes"] = len(content)
        record["checksum"] = _checksum(content)
        record["updated_at"] = now
        record["deleted"] = False
        record["uploaded"] = True
        return self._object_result(
            request,
            status="object_uploaded",
            record=record,
            required_next_step="head_object",
        )

    def replace_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._blocked_result(request, status="replace_not_implemented", next_step="implement_memory_replace")

    def delete_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        object_key, record = self._record_for_request(request)
        if not object_key:
            return self._blocked_result(request, status="object_handle_required", next_step="provide_object_handle")
        if record is None:
            return self._blocked_result(request, status="object_not_found", next_step="create_object")
        record["deleted"] = True
        record["updated_at"] = _utc_now()
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
        return self._blocked_result(
            request, status="generate_download_not_implemented", next_step="implement_memory_download"
        )

    def generate_upload(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._blocked_result(
            request, status="generate_upload_not_implemented", next_step="implement_memory_upload"
        )
