"""Document Lifecycle Orchestrator.

Coordinates the existing document, storage, processing, knowledge and search
runtime slices without introducing a new processing engine or worker pipeline.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.documents import Artifact, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution
from app.models.runtime_worker import RuntimeWorker
from app.schemas.documents import (
    DocumentBinaryUploadExecuteRequest,
    DocumentLifecycleOrchestrateRequest,
    DocumentVersionPlanRequest,
)
from app.services.document_binary_upload_execution import build_document_binary_upload_execution
from app.services.document_processing_control_plane import build_document_processing_enterprise_search
from app.services.document_organization_associations import (
    DocumentOrganizationAssociationService,
)
from app.services.document_processing_handoff import build_document_processing_handoff
from app.services.document_registration_execution import build_document_registration_execution
from app.services.document_version_planning import build_document_version_plan
from app.services.runtime_continuation import ContinuableRuntimeLifecycleService
from app.services.runtime_lifecycle import RuntimeLifecycleService
from app.services.storage_execution_control_plane import build_storage_execution_request_status

DOCUMENT_LIFECYCLE_ORCHESTRATOR_SCHEMA_VERSION = "1"
WORKER_HEARTBEAT_FRESHNESS = timedelta(minutes=10)
PROCESSING_RUNTIME_EXECUTION_TYPE = "document.indexing"
PROCESSING_RUNTIME_EXECUTION_SUFFIX = "processing-publication-index"


def _issue(code: str, message: str, *, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _warning(code: str, message: str, *, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "warning",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _content_bytes(payload: DocumentLifecycleOrchestrateRequest) -> tuple[bytes | None, list[dict[str, Any]]]:
    if payload.content_text is not None:
        return payload.content_text.encode("utf-8"), []
    if payload.content_bytes is not None:
        try:
            return base64.b64decode(payload.content_bytes, validate=True), []
        except Exception:
            return payload.content_bytes.encode("utf-8"), []
    return None, [
        _issue(
            "binary_content_required",
            "Document lifecycle orchestration requires content_text or content_bytes.",
            component="binary_upload",
        )
    ]


def _content_sha256(content: bytes | None) -> str | None:
    if content is None:
        return None
    return hashlib.sha256(content).hexdigest()


def _bounded_runtime_reference(prefix: str, *parts: str | None, max_length: int = 128) -> str:
    raw = ":".join(str(part) for part in parts if part)
    candidate = f"{prefix}:{raw}" if raw else prefix
    if len(candidate) <= max_length:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"[:max_length]


def _lifecycle_idempotency_key(
    payload: DocumentLifecycleOrchestrateRequest, content_sha256: str | None
) -> tuple[str, str]:
    if payload.idempotency_key and payload.idempotency_key.strip():
        return payload.idempotency_key.strip(), "client_supplied"
    seed = {
        "organization_id": str(payload.registration.organization_id),
        "external_reference": payload.registration.external_reference,
        "title": payload.registration.title,
        "version_label": payload.version_label,
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "content_sha256": content_sha256,
    }
    digest = hashlib.sha256(repr(sorted(seed.items())).encode("utf-8")).hexdigest()
    return f"document-lifecycle:{digest}", "derived_from_document_descriptor"


def _storage_provider_config(payload: DocumentLifecycleOrchestrateRequest) -> dict[str, Any]:
    config = dict(payload.storage_provider or {})
    filesystem_storage_root = get_settings().filesystem_storage_root
    if not config:
        return {
            "provider_name": "filesystem",
            "provider_type": "filesystem",
            "storage_root": filesystem_storage_root,
        }
    provider_name = (
        config.get("provider_name")
        or config.get("provider")
        or config.get("name")
        or config.get("provider_type")
        or config.get("type")
    )
    if not provider_name:
        config["provider_name"] = "filesystem"
        config["provider_type"] = "filesystem"
        config.setdefault("storage_root", filesystem_storage_root)
    return config


def _storage_provider_configured(payload: DocumentLifecycleOrchestrateRequest) -> bool:
    config = _storage_provider_config(payload)
    provider_name = (
        config.get("provider_name")
        or config.get("provider")
        or config.get("name")
        or config.get("provider_type")
        or config.get("type")
    )
    return isinstance(provider_name, str) and bool(provider_name.strip())


def _existing_version_by_lifecycle_key(
    db: Session, *, organization_id: uuid.UUID, lifecycle_key: str
) -> DocumentVersion | None:
    statement = (
        select(DocumentVersion)
        .where(
            DocumentVersion.organization_id == organization_id,
            DocumentVersion.source_snapshot["document_lifecycle_idempotency_key"].astext == lifecycle_key,
        )
        .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        .limit(1)
    )
    return db.scalars(statement).first()


def _read_version(version: DocumentVersion) -> dict[str, Any]:
    return {
        "document_version_id": str(version.id),
        "organization_id": str(version.organization_id),
        "document_record_id": str(version.document_record_id),
        "version_number": version.version_number,
        "version_label": version.version_label,
        "status": version.status,
        "content_type": version.content_type,
        "file_name": version.file_name,
        "size_bytes": version.size_bytes,
        "checksum_sha256": version.checksum_sha256,
        "object_store_provider": version.object_store_provider,
        "object_store_bucket": version.object_store_bucket,
        "object_store_key": version.object_store_key,
        "source_snapshot": version.source_snapshot or {},
    }


def _pending_binary_snapshot(
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    content_sha256: str | None,
    size_bytes: int | None = None,
) -> dict[str, Any]:
    return {
        "pending_file_name": payload.file_name,
        "pending_content_type": payload.content_type,
        "pending_size_bytes": size_bytes if size_bytes is not None else payload.size_bytes,
        "pending_checksum_sha256": content_sha256,
        "upload_executed": False,
        "binary_attached": False,
        "file_uploaded": False,
        "binary_uploaded": False,
        "storage_verified": False,
    }


def _should_normalize_lifecycle_version(version: DocumentVersion) -> bool:
    snapshot = version.source_snapshot or {}
    return (
        bool(snapshot.get("document_lifecycle_orchestrator"))
        and not bool(snapshot.get("storage_verified"))
        and version.object_store_provider is None
        and version.object_store_bucket is None
        and version.object_store_key is None
    )


def _normalize_lifecycle_version_pending_binary(
    db: Session,
    *,
    version: DocumentVersion,
    payload: DocumentLifecycleOrchestrateRequest,
    content_sha256: str | None,
    size_bytes: int | None = None,
) -> None:
    if not _should_normalize_lifecycle_version(version):
        return
    snapshot = dict(version.source_snapshot or {})
    snapshot.update(
        {
            **_pending_binary_snapshot(payload=payload, content_sha256=content_sha256, size_bytes=size_bytes),
            "pending_file_name": snapshot.get("pending_file_name") or version.file_name or payload.file_name,
            "pending_content_type": snapshot.get("pending_content_type")
            or version.content_type
            or payload.content_type,
            "pending_size_bytes": snapshot.get("pending_size_bytes")
            if snapshot.get("pending_size_bytes") is not None
            else version.size_bytes
            if version.size_bytes is not None
            else size_bytes
            if size_bytes is not None
            else payload.size_bytes,
            "pending_checksum_sha256": snapshot.get("pending_checksum_sha256")
            or version.checksum_sha256
            or content_sha256,
            "document_lifecycle_orchestrator": True,
        }
    )
    version.source_snapshot = snapshot
    version.content_type = None
    version.file_name = None
    version.size_bytes = None
    version.checksum_sha256 = None
    db.add(version)
    db.commit()
    db.refresh(version)


def _create_or_get_document_version(
    db: Session,
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    document_record_id: str,
    lifecycle_key: str,
    content_sha256: str | None,
    size_bytes: int | None = None,
) -> dict[str, Any]:
    existing = _existing_version_by_lifecycle_key(
        db, organization_id=payload.registration.organization_id, lifecycle_key=lifecycle_key
    )
    if existing is not None:
        _normalize_lifecycle_version_pending_binary(
            db,
            version=existing,
            payload=payload,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
        )
        return {
            "version_status": "already_executed",
            "document_version_created": False,
            "document_version": _read_version(existing),
            "document_version_id": str(existing.id),
            "blocking_issues": [],
            "warnings": [],
        }

    plan_payload = DocumentVersionPlanRequest(
        organization_id=payload.registration.organization_id,
        document_record_id=uuid.UUID(document_record_id),
        version_label=payload.version_label,
        requested_by=payload.requested_by or payload.registration.requested_by,
        metadata={
            **dict(payload.lifecycle_metadata or {}),
            "document_lifecycle_orchestrator": True,
            "document_lifecycle_idempotency_key": lifecycle_key,
            "content_sha256": content_sha256,
        },
    )
    plan = build_document_version_plan(db, payload=plan_payload)
    if not plan.get("can_create_new_version"):
        return {
            "version_status": "blocked",
            "document_version_created": False,
            "document_version": None,
            "document_version_id": None,
            "version_plan": plan,
            "blocking_issues": plan.get("blocking_issues") or [],
            "warnings": plan.get("warnings") or [],
        }
    candidate = plan.get("version_candidate") or {}
    version = DocumentVersion(
        organization_id=payload.registration.organization_id,
        document_record_id=uuid.UUID(document_record_id),
        version_number=int(candidate.get("version_number") or plan.get("next_version_number") or 1),
        version_label=payload.version_label,
        content_type=None,
        file_name=None,
        size_bytes=None,
        checksum_sha256=None,
        object_store_provider=None,
        object_store_bucket=None,
        object_store_key=None,
        source_snapshot={
            **dict(candidate.get("source_snapshot") or {}),
            **_pending_binary_snapshot(payload=payload, content_sha256=content_sha256, size_bytes=size_bytes),
            "document_lifecycle_orchestrator": True,
            "document_lifecycle_idempotency_key": lifecycle_key,
            "storage_provider": _storage_provider_config(payload),
            "lifecycle_metadata": dict(payload.lifecycle_metadata or {}),
        },
        status="registered",
        created_by=payload.requested_by or payload.registration.requested_by,
        updated_by=payload.requested_by or payload.registration.requested_by,
    )
    db.add(version)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_race = _existing_version_by_lifecycle_key(
            db,
            organization_id=payload.registration.organization_id,
            lifecycle_key=lifecycle_key,
        )
        if existing_after_race is None:
            raise
        _normalize_lifecycle_version_pending_binary(
            db,
            version=existing_after_race,
            payload=payload,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
        )
        return {
            "version_status": "already_executed_after_race",
            "document_version_created": False,
            "document_version": _read_version(existing_after_race),
            "document_version_id": str(existing_after_race.id),
            "version_plan": plan,
            "blocking_issues": [],
            "warnings": plan.get("warnings") or [],
        }
    db.refresh(version)
    return {
        "version_status": "executed",
        "document_version_created": True,
        "document_version": _read_version(version),
        "document_version_id": str(version.id),
        "version_plan": plan,
        "blocking_issues": [],
        "warnings": plan.get("warnings") or [],
    }


def _checksum_value(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("sha256:"):
        return value.split(":", 1)[1]
    return value


def _object_key(object_handle: dict[str, Any] | None) -> str | None:
    reference = (
        object_handle.get("reference")
        if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
        else {}
    )
    for key in ("object_key", "object_handle", "storage_key", "id"):
        value = reference.get(key) or (object_handle or {}).get(key)
        if value:
            return str(value)
    return None


def _object_container(object_handle: dict[str, Any] | None) -> str | None:
    reference = (
        object_handle.get("reference")
        if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
        else {}
    )
    value = reference.get("bucket") or reference.get("container") or reference.get("storage_root")
    return str(value) if value else None


def _provider_name(status: dict[str, Any]) -> str | None:
    descriptor = status.get("provider_descriptor") if isinstance(status.get("provider_descriptor"), dict) else {}
    return (
        status.get("storage_provider_name")
        or status.get("provider_name")
        or descriptor.get("provider_name")
        or descriptor.get("provider_type")
    )


def _provider_type(status: dict[str, Any]) -> str | None:
    descriptor = status.get("provider_descriptor") if isinstance(status.get("provider_descriptor"), dict) else {}
    return (
        status.get("storage_provider_type")
        or status.get("provider_type")
        or descriptor.get("provider_type")
        or descriptor.get("provider_name")
    )


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _storage_metadata_from_verification(verification: dict[str, Any]) -> dict[str, Any]:
    result_descriptor = (
        verification.get("result_descriptor") if isinstance(verification.get("result_descriptor"), dict) else {}
    )
    verification_descriptor = (
        verification.get("verification_descriptor")
        if isinstance(verification.get("verification_descriptor"), dict)
        else {}
    )
    execution_request = (
        verification.get("execution_request") if isinstance(verification.get("execution_request"), dict) else {}
    )
    storage_operation_result = (
        execution_request.get("storage_operation_result")
        if isinstance(execution_request.get("storage_operation_result"), dict)
        else {}
    )
    storage_operation_metadata = (
        storage_operation_result.get("metadata") if isinstance(storage_operation_result.get("metadata"), dict) else {}
    )
    object_handle = verification.get("object_handle") if isinstance(verification.get("object_handle"), dict) else None
    if object_handle is None:
        object_handle = (
            verification_descriptor.get("object_handle")
            if isinstance(verification_descriptor.get("object_handle"), dict)
            else None
        )
    if object_handle is None:
        object_handle = (
            result_descriptor.get("object_handle") if isinstance(result_descriptor.get("object_handle"), dict) else None
        )
    if object_handle is None:
        object_handle = (
            storage_operation_result.get("object_handle")
            if isinstance(storage_operation_result.get("object_handle"), dict)
            else None
        )
    return {
        "storage_verified": bool(
            verification.get("storage_verified") or verification_descriptor.get("storage_verified")
        ),
        "storage_verification_status": verification.get("storage_verification_status")
        or verification_descriptor.get("verification_status"),
        "storage_verification_available": bool(
            verification.get("storage_verification_available") or verification_descriptor.get("verification_available")
        ),
        "object_exists": bool(
            verification.get("object_exists")
            or result_descriptor.get("object_exists")
            or verification_descriptor.get("object_exists")
            or storage_operation_metadata.get("object_exists")
        ),
        "object_stored": bool(
            verification.get("object_stored")
            or result_descriptor.get("object_stored")
            or verification_descriptor.get("object_stored")
            or storage_operation_metadata.get("object_stored")
        ),
        "file_uploaded": bool(
            verification.get("file_uploaded")
            or result_descriptor.get("file_uploaded")
            or verification_descriptor.get("file_uploaded")
            or storage_operation_metadata.get("file_uploaded")
        ),
        "checksum_calculated": bool(
            verification.get("checksum_calculated")
            or result_descriptor.get("checksum_calculated")
            or verification_descriptor.get("checksum_calculated")
            or storage_operation_metadata.get("checksum_calculated")
        ),
        "checksum": verification.get("checksum")
        or result_descriptor.get("checksum")
        or verification_descriptor.get("checksum")
        or execution_request.get("checksum")
        or storage_operation_metadata.get("checksum"),
        "content_length": _first_not_none(
            verification.get("content_length"),
            result_descriptor.get("content_length"),
            verification_descriptor.get("content_length"),
            execution_request.get("content_length"),
            storage_operation_metadata.get("content_length"),
        ),
        "content_type": verification.get("content_type")
        or result_descriptor.get("content_type")
        or verification_descriptor.get("content_type")
        or execution_request.get("content_type")
        or storage_operation_metadata.get("content_type"),
        "object_handle": object_handle,
        "storage_provider_name": _provider_name(verification),
        "storage_provider_type": _provider_type(verification),
        "provider_descriptor": verification.get("provider_descriptor") or execution_request.get("provider_descriptor"),
        "storage_execution_request": execution_request,
        "storage_verification_result": verification.get("latest_storage_verification")
        or execution_request.get("storage_verification_result"),
        "storage_execution_result": result_descriptor,
    }


def _persist_storage_state(
    db: Session,
    *,
    artifact_id: str,
    document_version_id: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    metadata = _storage_metadata_from_verification(verification)
    artifact = db.get(Artifact, uuid.UUID(artifact_id))
    version = db.get(DocumentVersion, uuid.UUID(document_version_id))
    if artifact is None or version is None:
        return {
            "storage_state_persisted": False,
            "blocking_issues": [
                _issue(
                    "artifact_or_version_missing",
                    "Cannot persist lifecycle storage state without Artifact and DocumentVersion.",
                    component="document_lifecycle",
                )
            ],
        }
    current_metadata = dict(artifact.metadata_json or {})
    future_descriptor = dict(current_metadata.get("future_storage_descriptor") or {})
    future_descriptor["object_handle"] = metadata["object_handle"]
    object_container = _object_container(metadata["object_handle"])
    object_key = _object_key(metadata["object_handle"])
    checksum_sha256 = _checksum_value(metadata["checksum"])
    if metadata["storage_verified"]:
        missing_fields = []
        if not metadata["storage_provider_name"]:
            missing_fields.append("object_store_provider")
        if not object_container:
            missing_fields.append("object_store_bucket")
        if not object_key:
            missing_fields.append("object_store_key")
        if not checksum_sha256:
            missing_fields.append("checksum_sha256")
        if metadata["content_length"] is None:
            missing_fields.append("size_bytes")
        if not metadata["content_type"]:
            missing_fields.append("content_type")
        if missing_fields:
            return {
                "storage_state_persisted": False,
                "blocking_issues": [
                    _issue(
                        "storage_metadata_incomplete",
                        "Verified storage state is missing required persistent fields: " + ", ".join(missing_fields),
                        component="document_lifecycle",
                    )
                ],
            }
    current_metadata.update(
        {
            **{
                key: value
                for key, value in metadata.items()
                if key not in {"storage_execution_request", "storage_verification_result", "storage_execution_result"}
            },
            "upload_status": "storage_verified" if metadata["storage_verified"] else "uploaded",
            "storage_operation": "verify_object" if metadata["storage_verified"] else "upload_object",
            "upload_executed": metadata["file_uploaded"],
            "binary_attached": metadata["file_uploaded"],
            "file_uploaded": metadata["file_uploaded"],
            "document_lifecycle_orchestrator": True,
            "future_storage_descriptor": future_descriptor,
            "latest_storage_execution_request": metadata["storage_execution_request"],
            "latest_storage_verification": metadata["storage_verification_result"],
            "latest_storage_execution_result": metadata["storage_execution_result"],
            "processing_handoff_prerequisite_met": metadata["storage_verified"],
            "worker_runtime_ready": False,
            "worker_required": metadata["storage_verified"],
            "worker_execution_pending": metadata["storage_verified"],
            "publication_ready": False,
            "knowledge_publication_pending": metadata["storage_verified"],
            "enterprise_search_pending": metadata["storage_verified"],
        }
    )
    artifact.metadata_json = current_metadata
    artifact.object_store_provider = metadata["storage_provider_name"]
    artifact.bucket = object_container
    artifact.object_key = object_key
    artifact.checksum_sha256 = checksum_sha256
    artifact.size_bytes = metadata["content_length"]
    artifact.media_type = metadata["content_type"] or artifact.media_type
    artifact.status = "storage_verified" if metadata["storage_verified"] else "uploaded"
    version.content_type = metadata["content_type"] or version.content_type
    version.file_name = (version.source_snapshot or {}).get("pending_file_name") or version.file_name
    version.size_bytes = metadata["content_length"] if metadata["content_length"] is not None else version.size_bytes
    version.checksum_sha256 = checksum_sha256 or version.checksum_sha256
    version.object_store_provider = metadata["storage_provider_name"]
    version.object_store_bucket = object_container
    version.object_store_key = object_key
    version.source_snapshot = {
        **dict(version.source_snapshot or {}),
        "upload_executed": metadata["file_uploaded"],
        "binary_attached": metadata["file_uploaded"],
        "file_uploaded": metadata["file_uploaded"],
        "binary_uploaded": metadata["file_uploaded"],
        "storage_verified": metadata["storage_verified"],
        "object_handle": metadata["object_handle"],
        "object_store_provider": metadata["storage_provider_name"],
        "object_store_bucket": object_container,
        "object_store_key": object_key,
        "checksum": metadata["checksum"],
        "checksum_sha256": checksum_sha256,
        "size_bytes": metadata["content_length"],
        "content_type": metadata["content_type"],
        "document_lifecycle_orchestrator": True,
    }
    db.add(artifact)
    db.add(version)
    db.commit()
    return {
        "storage_state_persisted": True,
        "artifact_status": artifact.status,
        "document_version_status": version.status,
        "object_store_provider": artifact.object_store_provider,
        "object_store_bucket": artifact.bucket,
        "object_key": artifact.object_key,
        "object_store_key": artifact.object_key,
        "checksum_sha256": artifact.checksum_sha256,
        "size_bytes": artifact.size_bytes,
        "content_type": artifact.media_type,
        "storage_verified": metadata["storage_verified"],
        "upload_executed": metadata["file_uploaded"],
        "binary_attached": metadata["file_uploaded"],
        "file_uploaded": metadata["file_uploaded"],
        "worker_runtime_ready": False,
        "worker_required": metadata["storage_verified"],
        "worker_execution_pending": metadata["storage_verified"],
        "publication_ready": False,
        "knowledge_publication_pending": metadata["storage_verified"],
        "enterprise_search_pending": metadata["storage_verified"],
        "blocking_issues": [],
    }


def _existing_artifact_for_document_version(db: Session, *, document_version_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.document_version_id == uuid.UUID(str(document_version_id)))
        .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        .limit(1)
    )


def _version_storage_verified(version: DocumentVersion | None) -> bool:
    if version is None:
        return False
    snapshot = version.source_snapshot or {}
    return bool(
        snapshot.get("storage_verified") is True
        and version.object_store_key
        and version.object_store_provider
        and version.checksum_sha256
        and version.size_bytes is not None
    )


def _object_handle_from_persisted_storage(version: DocumentVersion, artifact: Artifact) -> dict[str, Any]:
    artifact_metadata = artifact.metadata_json or {}
    version_snapshot = version.source_snapshot or {}
    existing_handle = version_snapshot.get("object_handle")
    if isinstance(existing_handle, dict):
        return existing_handle
    future_descriptor = (
        artifact_metadata.get("future_storage_descriptor")
        if isinstance(artifact_metadata.get("future_storage_descriptor"), dict)
        else {}
    )
    existing_handle = future_descriptor.get("object_handle")
    if isinstance(existing_handle, dict):
        return existing_handle
    provider = artifact.object_store_provider or version.object_store_provider
    bucket = artifact.bucket or version.object_store_bucket
    key = artifact.object_key or version.object_store_key
    return {
        "provider": provider,
        "provider_name": provider,
        "provider_type": provider,
        "reference": {
            "bucket": bucket,
            "container": bucket,
            "storage_root": bucket,
            "object_key": key,
            "storage_key": key,
            "id": key,
        },
    }


def _reconstructed_storage_status_from_persisted_state(
    *,
    artifact: Artifact,
    version: DocumentVersion,
) -> dict[str, Any]:
    provider_name = artifact.object_store_provider or version.object_store_provider
    provider_type = provider_name or "filesystem"
    object_handle = _object_handle_from_persisted_storage(version, artifact)
    checksum = artifact.checksum_sha256 or version.checksum_sha256
    content_length = artifact.size_bytes if artifact.size_bytes is not None else version.size_bytes
    content_type = artifact.media_type or version.content_type
    upload_session_id = f"upload-session:{artifact.id}:{version.id}"
    execution_session_id = f"storage-execution-session:{artifact.id}:reuse"
    provider_descriptor = {
        "provider_name": provider_name,
        "provider_type": provider_type,
        "configured": True,
        "status": "available",
    }
    result_descriptor = {
        "storage_verified": True,
        "storage_verification_status": "storage_verified",
        "storage_verification_available": True,
        "object_exists": True,
        "object_stored": True,
        "file_uploaded": True,
        "checksum_calculated": True,
        "checksum": checksum,
        "content_length": content_length,
        "content_type": content_type,
        "object_handle": object_handle,
    }
    storage_execution_session = {
        "execution_session_id": execution_session_id,
        "artifact_id": str(artifact.id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(version.id),
        "requested_operation": "verify_object",
        "execution_status": "storage_verified",
        "storage_verified": True,
    }
    upload_session = {
        "upload_session_id": upload_session_id,
        "artifact_id": str(artifact.id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(version.id),
        "execution_flags": {
            "file_uploaded": True,
            "object_stored": True,
            "checksum_calculated": True,
            "ingestion_executed": False,
            "chunks_created": False,
            "embeddings_created": False,
            "ai_required": False,
            "vector_store_required": False,
        },
    }
    execution_request = {
        **result_descriptor,
        "artifact_id": str(artifact.id),
        "upload_session_id": upload_session_id,
        "execution_session_id": execution_session_id,
        "storage_execution_session": storage_execution_session,
        "upload_session": upload_session,
        "provider_descriptor": provider_descriptor,
        "requested_operation": "verify_object",
        "storage_verified": True,
        "processing_handoff_prerequisite_met": True,
        "processing_handoff_allowed": False,
    }
    return {
        "artifact_id": str(artifact.id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(version.id),
        "upload_session_id": upload_session_id,
        "execution_session_id": execution_session_id,
        "requested_operation": "verify_object",
        "execution_status": "storage_verified",
        "storage_verified": True,
        "storage_reused": True,
        "storage_reuse_status_reconstructed": True,
        "processing_handoff_prerequisite_met": True,
        "processing_handoff_allowed": False,
        "object_exists": True,
        "object_stored": True,
        "file_uploaded": True,
        "checksum_calculated": True,
        "checksum": checksum,
        "content_length": content_length,
        "size_bytes": content_length,
        "content_type": content_type,
        "object_handle": object_handle,
        "provider_descriptor": provider_descriptor,
        "storage_provider_name": provider_name,
        "storage_provider_type": provider_type,
        "result_descriptor": result_descriptor,
        "verification_descriptor": result_descriptor,
        "storage_verification_status": "storage_verified",
        "storage_verification_available": True,
        "storage_execution_session": storage_execution_session,
        "upload_session": upload_session,
        "execution_request": execution_request,
        "blocking_issues": [],
        "warnings": [],
    }


def _storage_reuse_contract_issues(storage_status: dict[str, Any]) -> list[dict[str, Any]]:
    required_truthy = (
        "storage_verified",
        "processing_handoff_prerequisite_met",
        "object_exists",
        "object_stored",
        "file_uploaded",
        "checksum_calculated",
        "object_handle",
        "checksum",
        "content_length",
        "content_type",
        "storage_provider_name",
        "storage_provider_type",
        "provider_descriptor",
        "storage_verification_status",
        "storage_verification_available",
        "storage_execution_session",
        "execution_request",
        "result_descriptor",
        "verification_descriptor",
        "artifact_id",
        "upload_session_id",
        "execution_session_id",
    )
    issues: list[dict[str, Any]] = []
    for field_name in required_truthy:
        value = storage_status.get(field_name)
        if field_name == "content_length":
            missing = value is None
        elif field_name == "storage_verification_status":
            missing = value != "storage_verified"
        else:
            missing = not bool(value)
        if missing:
            issues.append(
                _issue(
                    "storage_reuse_status_incomplete",
                    f"Reconstructed storage status is missing required field: {field_name}.",
                    component="storage_reuse",
                    item_id=field_name,
                )
            )
    execution_session = storage_status.get("storage_execution_session")
    if not isinstance(execution_session, dict) or not execution_session.get("execution_session_id"):
        issues.append(
            _issue(
                "storage_reuse_status_incomplete",
                "Reconstructed storage status requires storage_execution_session.execution_session_id.",
                component="storage_reuse",
                item_id="storage_execution_session.execution_session_id",
            )
        )
    return _sort_issues(issues)


def _strict_runtime_required(payload: DocumentLifecycleOrchestrateRequest) -> bool:
    lifecycle_metadata = payload.lifecycle_metadata or {}
    publication_config = payload.publication_config or {}
    return bool(lifecycle_metadata.get("reference_tenant") or publication_config.get("reference_tenant"))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _knowledge_index_payload(processing_publication_search: dict[str, Any]) -> dict[str, Any]:
    knowledge_index = processing_publication_search.get("knowledge_index")
    return knowledge_index if isinstance(knowledge_index, dict) else {}


def _knowledge_index_summary(processing_publication_search: dict[str, Any]) -> dict[str, Any]:
    knowledge_index = _knowledge_index_payload(processing_publication_search)
    document = knowledge_index.get("knowledge_document")
    document_payload = document if isinstance(document, dict) else {}
    chunks = knowledge_index.get("knowledge_chunks")
    chunk_payloads = chunks if isinstance(chunks, list) else []
    knowledge_document_ids = [
        str(item.get("knowledge_document_id") or item.get("id"))
        for item in ([document_payload] if document_payload else [])
        if item.get("knowledge_document_id") or item.get("id")
    ]
    chunks_indexed = _int_value(knowledge_index.get("chunks_indexed"))
    if chunks_indexed <= 0:
        chunks_indexed = len(chunk_payloads)
    chunks_created = _int_value(knowledge_index.get("chunks_created"))
    chunks_updated = _int_value(knowledge_index.get("chunks_updated"))
    persistence_status = knowledge_index.get("persistence_status")
    document_indexed = bool(knowledge_index.get("document_indexed") or document_payload)
    knowledge_document_id = document_payload.get("knowledge_document_id") or document_payload.get("id")
    persisted_contract_reported = bool(
        knowledge_index.get("index_succeeded")
        and (persistence_status in (None, "persisted") or knowledge_index.get("index_completed"))
    )
    legacy_contract_reported = bool(
        not knowledge_index
        and processing_publication_search.get("index_succeeded")
        and processing_publication_search.get("index_completed") in (None, True)
    )
    persisted_document_evidence = bool(knowledge_document_id and chunks_indexed > 0)
    lineage_complete = bool(
        document_payload.get("document_record_id")
        and document_payload.get("document_version_id")
        and persisted_document_evidence
    )
    knowledge_indexed = bool(lineage_complete and (persisted_contract_reported or legacy_contract_reported))
    blocking_issues = [issue for issue in knowledge_index.get("blocking_issues") or [] if isinstance(issue, dict)]
    warnings = [warning for warning in knowledge_index.get("warnings") or [] if isinstance(warning, dict)]
    status = (
        knowledge_index.get("knowledge_index_status")
        or knowledge_index.get("status")
        or ("indexed" if knowledge_indexed else "pending")
    )
    return {
        "knowledge_indexed": knowledge_indexed,
        "knowledge_lineage_complete": lineage_complete,
        "index_succeeded": bool(knowledge_index.get("index_succeeded") or knowledge_indexed),
        "index_completed": bool(knowledge_index.get("index_completed") or knowledge_indexed),
        "document_indexed": document_indexed,
        "knowledge_document_id": knowledge_document_id,
        "knowledge_document_ids": knowledge_document_ids,
        "publication_id": document_payload.get("publication_id") or processing_publication_search.get("publication_id"),
        "knowledge_chunk_count": chunks_indexed,
        "knowledge_chunks_indexed": chunks_indexed,
        "knowledge_chunks_created": chunks_created,
        "knowledge_chunks_updated": chunks_updated,
        "knowledge_index_status": status,
        "knowledge_index_blocking_issues": _sort_issues(blocking_issues),
        "knowledge_index_warnings": _sort_issues(warnings),
    }


def _enterprise_search_summary(
    processing_publication_search: dict[str, Any], knowledge_index_summary: dict[str, Any]
) -> dict[str, Any]:
    enterprise_search = processing_publication_search.get("enterprise_search")
    enterprise_search_payload = enterprise_search if isinstance(enterprise_search, dict) else {}
    search_result = processing_publication_search.get("search_result")
    search_result_payload = search_result if isinstance(search_result, dict) else {}
    result_count = _int_value(
        processing_publication_search.get("result_count")
        if processing_publication_search.get("result_count") is not None
        else enterprise_search_payload.get("result_count")
        if enterprise_search_payload.get("result_count") is not None
        else search_result_payload.get("result_count")
    )
    search_succeeded = bool(
        processing_publication_search.get("search_succeeded")
        or enterprise_search_payload.get("search_succeeded")
        or search_result_payload.get("search_succeeded")
    )
    knowledge_indexed = bool(knowledge_index_summary.get("knowledge_indexed"))
    search_index_contract_inconsistent = bool(result_count > 0 and not knowledge_indexed)
    return {
        "enterprise_search_ready": bool(
            search_succeeded and result_count > 0 and knowledge_indexed and not search_index_contract_inconsistent
        ),
        "search_succeeded": search_succeeded,
        "search_result_count": result_count,
        "search_index_contract_inconsistent": search_index_contract_inconsistent,
    }


def _knowledge_document_id(processing_publication_search: dict[str, Any]) -> str | None:
    value = _knowledge_index_summary(processing_publication_search).get("knowledge_document_id")
    return str(value) if value else None


def _knowledge_chunk_count(processing_publication_search: dict[str, Any]) -> int:
    return _int_value(_knowledge_index_summary(processing_publication_search).get("knowledge_chunk_count"))


def _processing_publication_search_issues(processing_publication_search: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key in ("blocking_issues",):
        for issue in processing_publication_search.get(key) or []:
            if isinstance(issue, dict):
                issues.append(issue)
    nested_components = (
        "processing_execution",
        "chunk_generation",
        "knowledge_publication",
        "knowledge_index",
        "enterprise_search",
        "search_result",
    )
    for component in nested_components:
        nested = processing_publication_search.get(component)
        if isinstance(nested, dict):
            for issue in nested.get("blocking_issues") or []:
                if isinstance(issue, dict):
                    issues.append({**issue, "runtime_stage": component})
    knowledge_index_summary = _knowledge_index_summary(processing_publication_search)
    enterprise_search_summary = _enterprise_search_summary(processing_publication_search, knowledge_index_summary)
    if enterprise_search_summary.get("search_index_contract_inconsistent"):
        issues.append(
            _issue(
                "search_index_contract_inconsistent",
                "Enterprise Search returned results without a persisted PostgreSQL Knowledge Index contract.",
                component="enterprise_search",
            )
        )
    required_flags = {
        "processing_completed": ("processing_runtime", bool(processing_publication_search.get("processing_completed"))),
        "chunks_created": ("chunk_generation", bool(processing_publication_search.get("chunks_created"))),
        "knowledge_published": (
            "knowledge_publication",
            bool(processing_publication_search.get("knowledge_published")),
        ),
        "index_succeeded": ("knowledge_index", bool(knowledge_index_summary.get("knowledge_indexed"))),
        "search_succeeded": ("enterprise_search", bool(enterprise_search_summary.get("enterprise_search_ready"))),
    }
    for flag, (component, satisfied) in required_flags.items():
        if not satisfied:
            issues.append(
                _issue(
                    f"{flag}_required",
                    f"Strict document lifecycle requires {flag}=true.",
                    component=component,
                )
            )
    return _sort_issues(issues)


def _lifecycle_completed_from_processing(processing_publication_search: dict[str, Any]) -> bool:
    knowledge_index_summary = _knowledge_index_summary(processing_publication_search)
    enterprise_search_summary = _enterprise_search_summary(processing_publication_search, knowledge_index_summary)
    return bool(
        processing_publication_search.get("processing_completed")
        and processing_publication_search.get("chunks_created")
        and processing_publication_search.get("knowledge_published")
        and knowledge_index_summary.get("knowledge_indexed")
        and enterprise_search_summary.get("enterprise_search_ready")
    )


def _publication_index_completed_from_processing(processing_publication_search: dict[str, Any]) -> bool:
    knowledge_index_summary = _knowledge_index_summary(processing_publication_search)
    return bool(
        processing_publication_search.get("processing_completed")
        and processing_publication_search.get("chunks_created")
        and processing_publication_search.get("knowledge_published")
        and knowledge_index_summary.get("knowledge_indexed")
    )


def _latest_runtime_execution_for_document_version(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_version_id: str,
) -> RuntimeExecution | None:
    try:
        version_uuid = uuid.UUID(str(document_version_id))
    except (TypeError, ValueError):
        return None
    return db.scalar(
        select(RuntimeExecution)
        .where(
            RuntimeExecution.organization_id == organization_id,
            RuntimeExecution.subject_id == version_uuid,
            RuntimeExecution.execution_type == PROCESSING_RUNTIME_EXECUTION_TYPE,
        )
        .order_by(RuntimeExecution.created_at.desc(), RuntimeExecution.id.desc())
        .limit(1)
    )


def _runtime_execution_snapshot(execution: RuntimeExecution | None) -> dict[str, Any]:
    if execution is None:
        return {
            "runtime_execution_id": None,
            "runtime_execution_type": None,
            "runtime_execution_status": None,
            "runtime_execution_terminal": False,
            "runtime_execution_succeeded": False,
            "runtime_execution_failed": False,
            "runtime_execution_error_code": None,
            "runtime_execution_error_message": None,
        }
    return {
        "runtime_execution_id": str(execution.id),
        "runtime_execution_type": execution.execution_type,
        "runtime_execution_status": execution.status,
        "runtime_execution_terminal": execution.status
        in {"succeeded", "failed", "cancelled", "dead_lettered"},
        "runtime_execution_succeeded": execution.status == "succeeded",
        "runtime_execution_failed": execution.status in {"failed", "dead_lettered"},
        "runtime_execution_error_code": execution.error_code,
        "runtime_execution_error_message": execution.error_message,
    }


def _worker_runtime_inventory(db: Session) -> dict[str, Any]:
    workers = db.scalars(select(RuntimeWorker)).all()
    fresh_after = _utcnow() - WORKER_HEARTBEAT_FRESHNESS
    ready_workers = [
        worker
        for worker in workers
        if worker.desired_state == "active"
        and worker.observed_state in {"ready", "busy"}
        and worker.heartbeat_at is not None
        and worker.heartbeat_at >= fresh_after
    ]
    return {
        "worker_runtime_registered": bool(workers),
        "worker_runtime_ready": bool(ready_workers),
        "worker_count": len(workers),
        "ready_worker_count": len(ready_workers),
        "worker_freshness_seconds": int(WORKER_HEARTBEAT_FRESHNESS.total_seconds()),
    }


def _worker_lifecycle_status(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_version_id: str,
    orchestration_prepared: bool,
    lifecycle_completed: bool,
    processing_publication_search: dict[str, Any],
) -> dict[str, Any]:
    execution = _latest_runtime_execution_for_document_version(
        db,
        organization_id=organization_id,
        document_version_id=document_version_id,
    )
    execution_snapshot = _runtime_execution_snapshot(execution)
    worker_inventory = _worker_runtime_inventory(db)
    processing_attempted = bool(processing_publication_search)
    worker_execution_pending = bool(orchestration_prepared and not lifecycle_completed)
    runtime_ready = bool(
        lifecycle_completed
        or execution_snapshot["runtime_execution_succeeded"]
        or worker_inventory["worker_runtime_ready"]
    )
    return {
        **worker_inventory,
        **execution_snapshot,
        "worker_required": bool(orchestration_prepared),
        "worker_execution_pending": worker_execution_pending,
        "worker_runtime_ready": runtime_ready,
        "processing_publication_search_attempted": processing_attempted,
        "processing_publication_search_completed": bool(
            _publication_index_completed_from_processing(processing_publication_search)
        ),
    }


def _processing_runtime_input_payload(
    *,
    artifact_id: str,
    document_record_id: str,
    document_version_id: str,
    lifecycle_key: str,
    verification: dict[str, Any],
    payload: DocumentLifecycleOrchestrateRequest,
) -> dict[str, Any]:
    chunk_signature = {
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "checksum_sha256": verification.get("checksum"),
        "content_length": verification.get("content_length"),
        "chunker_config": dict(payload.chunker_config or {}),
        "publication_config": dict(payload.publication_config or {}),
        "search_config": dict(payload.search_config or {}),
    }
    return {
        "artifact_id": artifact_id,
        "document_id": document_record_id,
        "document_record_id": document_record_id,
        "document_version_id": document_version_id,
        "document_lifecycle_idempotency_key": lifecycle_key,
        "chunk_signature": chunk_signature,
        "storage_verified": bool(verification.get("storage_verified")),
        "storage_execution_status": {
            key: verification.get(key)
            for key in (
                "artifact_id",
                "upload_session_id",
                "execution_session_id",
                "storage_verified",
                "object_handle",
                "checksum",
                "content_length",
                "content_type",
                "storage_provider_name",
                "storage_provider_type",
            )
        },
        "query": payload.search_query,
        "top_k": payload.top_k,
    }


def _create_or_get_processing_runtime_execution(
    db: Session,
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    lifecycle_key: str,
    artifact_id: str,
    document_record_id: str,
    document_version_id: str,
    verification: dict[str, Any],
) -> tuple[RuntimeExecution | None, bool, list[dict[str, Any]]]:
    try:
        execution, created = RuntimeLifecycleService(db).create_or_get(
            organization_id=payload.registration.organization_id,
            execution_type=PROCESSING_RUNTIME_EXECUTION_TYPE,
            subject_type="document_version",
            subject_id=uuid.UUID(str(document_version_id)),
            idempotency_key=_bounded_runtime_reference(
                "document-lifecycle-runtime",
                lifecycle_key,
                document_version_id,
                PROCESSING_RUNTIME_EXECUTION_SUFFIX,
            ),
            requested_by=payload.requested_by or payload.registration.requested_by,
            correlation_id=_bounded_runtime_reference("document-lifecycle", lifecycle_key),
            priority=100,
            input_payload=_processing_runtime_input_payload(
                artifact_id=artifact_id,
                document_record_id=document_record_id,
                document_version_id=document_version_id,
                lifecycle_key=lifecycle_key,
                verification=verification,
                payload=payload,
            ),
            policy_snapshot={
                "postgresql_source_of_truth": True,
                "llm_used": False,
                "embeddings_used": False,
                "qdrant_used": False,
                "document_lifecycle_orchestrator": True,
            },
        )
        db.commit()
        return execution, created, []
    except Exception as exc:
        db.rollback()
        return (
            None,
            False,
            [
                _issue(
                    "PROCESSING_RUNTIME_EXECUTION_CREATE_FAILED",
                    str(exc),
                    component="worker_runtime",
                    item_id=exc.__class__.__name__,
                )
            ],
        )


def _claim_processing_runtime_execution(
    db: Session,
    *,
    execution: RuntimeExecution,
    worker_id: str,
) -> tuple[Any | None, list[dict[str, Any]]]:
    if execution.status == "succeeded":
        return None, []
    if execution.status in {"failed", "cancelled", "dead_lettered"}:
        return (
            None,
            [
                _issue(
                    "PROCESSING_RUNTIME_EXECUTION_FAILED",
                    execution.error_message or "Processing runtime execution is terminal and not successful.",
                    component="worker_runtime",
                    item_id=str(execution.id),
                )
            ],
        )
    if execution.status not in {"pending", "scheduled", "expired", "leased", "running"}:
        return None, []
    try:
        claimed = ContinuableRuntimeLifecycleService(db).claim_selected(
            organization_id=execution.organization_id,
            execution_id=execution.id,
            worker_id=worker_id,
            lease_duration=timedelta(minutes=5),
        )
        db.commit()
        return claimed, []
    except Exception as exc:
        db.rollback()
        return (
            None,
            [
                _issue(
                    "PROCESSING_RUNTIME_EXECUTION_CLAIM_FAILED",
                    str(exc),
                    component="worker_runtime",
                    item_id=exc.__class__.__name__,
                )
            ],
        )


def _complete_processing_runtime_execution(
    db: Session,
    *,
    execution: RuntimeExecution,
    attempt: Any,
    processing_publication_search: dict[str, Any],
) -> tuple[RuntimeExecution | None, list[dict[str, Any]]]:
    lifecycle_complete = _publication_index_completed_from_processing(processing_publication_search)
    try:
        RuntimeLifecycleService(db).start(
            execution.organization_id,
            execution.id,
            lease_token=attempt.lease_token,
        )
        if lifecycle_complete:
            completed = RuntimeLifecycleService(db).succeed(
                execution.organization_id,
                execution.id,
                lease_token=attempt.lease_token,
                metrics={
                    "processing_completed": bool(processing_publication_search.get("processing_completed")),
                    "chunks_created": bool(processing_publication_search.get("chunks_created")),
                    "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
                    "knowledge_indexed": bool(
                        _knowledge_index_summary(processing_publication_search).get("knowledge_indexed")
                    ),
                    "enterprise_search_ready": bool(
                        _enterprise_search_summary(
                            processing_publication_search,
                            _knowledge_index_summary(processing_publication_search),
                        ).get("enterprise_search_ready")
                    ),
                },
            )
        else:
            issues = _processing_publication_search_issues(processing_publication_search)
            first_issue = issues[0] if issues else {}
            completed = RuntimeLifecycleService(db).fail(
                execution.organization_id,
                execution.id,
                lease_token=attempt.lease_token,
                error_code=str(first_issue.get("code") or "PROCESSING_PUBLICATION_INDEX_NOT_COMPLETED"),
                error_message=str(
                    first_issue.get("message") or "Processing/publication/index runtime did not complete."
                ),
                metrics={
                    "processing_completed": bool(processing_publication_search.get("processing_completed")),
                    "chunks_created": bool(processing_publication_search.get("chunks_created")),
                    "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
                    "index_succeeded": bool(processing_publication_search.get("index_succeeded")),
                },
            )
        db.commit()
        return completed, []
    except Exception as exc:
        db.rollback()
        return (
            None,
            [
                _issue(
                    "PROCESSING_RUNTIME_EXECUTION_COMPLETE_FAILED",
                    str(exc),
                    component="worker_runtime",
                    item_id=exc.__class__.__name__,
                )
            ],
        )


def _processing_publication_search_with_runtime_execution(
    db: Session,
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    lifecycle_key: str,
    artifact_id: str,
    document_record_id: str,
    document_version_id: str,
    verification: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    execution, created, issues = _create_or_get_processing_runtime_execution(
        db,
        payload=payload,
        lifecycle_key=lifecycle_key,
        artifact_id=artifact_id,
        document_record_id=document_record_id,
        document_version_id=document_version_id,
        verification=verification,
    )
    if execution is None:
        return None, {"runtime_execution_created": created}, issues

    runtime_snapshot = {
        **_runtime_execution_snapshot(execution),
        "runtime_execution_created": created,
    }
    claimed, claim_issues = _claim_processing_runtime_execution(
        db,
        execution=execution,
        worker_id="document-lifecycle-orchestrator",
    )
    if claim_issues:
        return None, runtime_snapshot, claim_issues
    if claimed is None and execution.status != "succeeded":
        return None, runtime_snapshot, [
            _issue(
                "PROCESSING_RUNTIME_EXECUTION_NOT_CLAIMABLE",
                "Processing runtime execution exists but is not claimable or terminal successful.",
                component="worker_runtime",
                item_id=str(execution.id),
            )
        ]

    processing_publication_search = build_document_processing_enterprise_search(
        db,
        artifact_id=uuid.UUID(str(artifact_id)),
        query=payload.search_query,
        top_k=payload.top_k,
        storage_execution_status=verification,
        chunker_config=payload.chunker_config,
        publication_config=payload.publication_config,
        search_config=payload.search_config,
    )
    if claimed is not None:
        claimed_execution, attempt = claimed
        completed, completion_issues = _complete_processing_runtime_execution(
            db,
            execution=claimed_execution,
            attempt=attempt,
            processing_publication_search=processing_publication_search or {},
        )
        if completion_issues:
            return processing_publication_search, runtime_snapshot, completion_issues
        if completed is not None:
            runtime_snapshot = {
                **_runtime_execution_snapshot(completed),
                "runtime_execution_created": created,
            }
    return processing_publication_search, runtime_snapshot, []


def _persisted_storage_state_response(*, artifact: Artifact, version: DocumentVersion) -> dict[str, Any]:
    snapshot = version.source_snapshot or {}
    lifecycle_complete = bool(snapshot.get("knowledge_indexed"))
    worker_execution_pending = bool(snapshot.get("storage_verified") and not lifecycle_complete)
    return {
        "storage_state_persisted": True,
        "storage_reused": True,
        "artifact_status": artifact.status,
        "document_version_status": version.status,
        "object_store_provider": artifact.object_store_provider or version.object_store_provider,
        "object_store_bucket": artifact.bucket or version.object_store_bucket,
        "object_key": artifact.object_key or version.object_store_key,
        "object_store_key": artifact.object_key or version.object_store_key,
        "checksum_sha256": artifact.checksum_sha256 or version.checksum_sha256,
        "size_bytes": artifact.size_bytes if artifact.size_bytes is not None else version.size_bytes,
        "content_type": artifact.media_type or version.content_type,
        "storage_verified": True,
        "upload_executed": True,
        "binary_attached": True,
        "file_uploaded": True,
        "worker_runtime_ready": bool(snapshot.get("worker_runtime_ready") or lifecycle_complete),
        "worker_required": bool(snapshot.get("storage_verified")),
        "worker_execution_pending": worker_execution_pending,
        "publication_ready": bool(snapshot.get("knowledge_published")),
        "knowledge_publication_pending": not bool(snapshot.get("knowledge_published")),
        "enterprise_search_pending": not bool(snapshot.get("enterprise_search_visible")),
        "blocking_issues": [],
    }


def _persist_lifecycle_completion_state(
    db: Session,
    *,
    document_version_id: str,
    processing_publication_search: dict[str, Any],
    storage_reused: bool,
    storage_reuse_status_complete: bool,
    processing_handoff_ready: bool,
    processing_handoff_blocking_issues: list[dict[str, Any]],
) -> None:
    version = db.get(DocumentVersion, uuid.UUID(str(document_version_id)))
    if version is None:
        return
    snapshot = dict(version.source_snapshot or {})
    knowledge_index_summary = _knowledge_index_summary(processing_publication_search)
    enterprise_search_summary = _enterprise_search_summary(processing_publication_search, knowledge_index_summary)
    enterprise_search_ready = bool(enterprise_search_summary.get("enterprise_search_ready"))
    enterprise_search_issues = (
        [
            _issue(
                "search_index_contract_inconsistent",
                "Enterprise Search returned results without a persisted PostgreSQL Knowledge Index contract.",
                component="enterprise_search",
            )
        ]
        if enterprise_search_summary.get("search_index_contract_inconsistent")
        else []
    )
    lifecycle_blocking_issues = _sort_issues(
        [
            *(processing_publication_search.get("blocking_issues") or []),
            *(knowledge_index_summary.get("knowledge_index_blocking_issues") or []),
            *enterprise_search_issues,
        ]
    )
    lifecycle_warnings = _sort_issues(
        [
            *(processing_publication_search.get("warnings") or []),
            *(knowledge_index_summary.get("knowledge_index_warnings") or []),
        ]
    )
    lifecycle_completed = _publication_index_completed_from_processing(processing_publication_search)
    worker_execution_pending = bool(snapshot.get("storage_verified") and not lifecycle_completed)
    reference_tenant_summary = {
        "storage_reused": bool(storage_reused),
        "storage_verified": bool(snapshot.get("storage_verified")),
        "processing_completed": bool(processing_publication_search.get("processing_completed")),
        "chunks_created": bool(processing_publication_search.get("chunks_created")),
        "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
        "knowledge_indexed": bool(knowledge_index_summary.get("knowledge_indexed")),
        "knowledge_document_id": knowledge_index_summary.get("knowledge_document_id"),
        "knowledge_document_ids": knowledge_index_summary.get("knowledge_document_ids") or [],
        "publication_id": knowledge_index_summary.get("publication_id"),
        "knowledge_chunk_count": knowledge_index_summary.get("knowledge_chunk_count"),
        "knowledge_chunks_indexed": knowledge_index_summary.get("knowledge_chunks_indexed"),
        "knowledge_chunks_created": knowledge_index_summary.get("knowledge_chunks_created"),
        "knowledge_chunks_updated": knowledge_index_summary.get("knowledge_chunks_updated"),
        "knowledge_index_status": knowledge_index_summary.get("knowledge_index_status"),
        "knowledge_index_blocking_issues": knowledge_index_summary.get("knowledge_index_blocking_issues") or [],
        "knowledge_index_warnings": knowledge_index_summary.get("knowledge_index_warnings") or [],
        "enterprise_search_ready": enterprise_search_ready,
        "search_result_count": enterprise_search_summary.get("search_result_count"),
        "search_index_contract_inconsistent": enterprise_search_summary.get("search_index_contract_inconsistent"),
        "chat_ready": enterprise_search_ready,
        "worker_required": bool(snapshot.get("storage_verified")),
        "worker_runtime_ready": bool(lifecycle_completed),
        "worker_execution_pending": worker_execution_pending,
        "blocking_issues": lifecycle_blocking_issues,
        "warnings": lifecycle_warnings,
    }
    snapshot.update(
        {
            "processing_ready": bool(processing_publication_search.get("processing_completed")),
            "chunks_created": bool(processing_publication_search.get("chunks_created")),
            "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
            "knowledge_indexed": bool(knowledge_index_summary.get("knowledge_indexed")),
            "enterprise_search_visible": enterprise_search_ready,
            "chat_ready": enterprise_search_ready,
            "knowledge_document_id": knowledge_index_summary.get("knowledge_document_id"),
            "knowledge_document_ids": knowledge_index_summary.get("knowledge_document_ids") or [],
            "publication_id": knowledge_index_summary.get("publication_id"),
            "knowledge_chunk_count": knowledge_index_summary.get("knowledge_chunk_count"),
            "knowledge_chunks_indexed": knowledge_index_summary.get("knowledge_chunks_indexed"),
            "knowledge_chunks_created": knowledge_index_summary.get("knowledge_chunks_created"),
            "knowledge_chunks_updated": knowledge_index_summary.get("knowledge_chunks_updated"),
            "knowledge_index_status": knowledge_index_summary.get("knowledge_index_status"),
            "knowledge_index_blocking_issues": knowledge_index_summary.get("knowledge_index_blocking_issues") or [],
            "knowledge_index_warnings": knowledge_index_summary.get("knowledge_index_warnings") or [],
            "search_result_count": enterprise_search_summary.get("search_result_count"),
            "search_index_contract_inconsistent": enterprise_search_summary.get("search_index_contract_inconsistent"),
            "storage_reused": bool(storage_reused),
            "storage_reuse_status_complete": bool(storage_reuse_status_complete),
            "processing_handoff_ready": bool(processing_handoff_ready),
            "processing_handoff_blocking_issues": list(processing_handoff_blocking_issues or []),
            "worker_required": bool(snapshot.get("storage_verified")),
            "worker_runtime_ready": bool(lifecycle_completed),
            "worker_execution_pending": worker_execution_pending,
            "worker_execution_completed": bool(lifecycle_completed),
            "document_lifecycle_completed": bool(lifecycle_completed),
            "reference_tenant_lifecycle_summary": reference_tenant_summary,
        }
    )
    version.source_snapshot = snapshot
    db.add(version)
    artifact = _existing_artifact_for_document_version(db, document_version_id=str(version.id))
    if artifact is not None:
        artifact_metadata = dict(artifact.metadata_json or {})
        artifact_metadata.update(
            {
                "worker_required": bool(snapshot.get("storage_verified")),
                "worker_runtime_ready": bool(lifecycle_completed),
                "worker_execution_pending": worker_execution_pending,
                "worker_execution_completed": bool(lifecycle_completed),
                "processing_ready": bool(processing_publication_search.get("processing_completed")),
                "chunks_created": bool(processing_publication_search.get("chunks_created")),
                "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
                "knowledge_indexed": bool(knowledge_index_summary.get("knowledge_indexed")),
                "enterprise_search_visible": enterprise_search_ready,
                "chat_ready": enterprise_search_ready,
                "reference_tenant_lifecycle_summary": reference_tenant_summary,
            }
        )
        artifact.metadata_json = artifact_metadata
        db.add(artifact)
    db.commit()


def _block_response(
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    lifecycle_key: str,
    lifecycle_key_source: str,
    blocking_issues: list[dict[str, Any]],
    warnings: list[dict[str, Any]] | None = None,
    stages: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage_diagnostics = _storage_execution_diagnostics(stages or {})
    if (
        storage_diagnostics.get("storage_execution_attempted")
        and storage_diagnostics.get("storage_execution_blocking_issue") is None
    ):
        storage_diagnostics["storage_execution_blocking_issue"] = blocking_issues[0] if blocking_issues else None
    return {
        "document_lifecycle_orchestrator_schema_version": DOCUMENT_LIFECYCLE_ORCHESTRATOR_SCHEMA_VERSION,
        "lifecycle_status": "blocked",
        "lifecycle_completed": False,
        "organization_id": str(payload.registration.organization_id),
        "idempotency": {
            "key": lifecycle_key,
            "source": lifecycle_key_source,
        },
        "stages": stages or {},
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": warnings or [],
        "document_registered": False,
        "document_version_ready": False,
        "binary_uploaded": False,
        "upload_executed": False,
        "binary_attached": False,
        "file_uploaded": False,
        "storage_verified": False,
        **storage_diagnostics,
        "processing_ready": False,
        "worker_runtime_ready": False,
        "publication_ready": False,
        "knowledge_indexed": False,
        "enterprise_search_visible": False,
        "assistant_chat_available": False,
        "ai_required": False,
        "embeddings_required": False,
    }


def _stage_blocking_issue(stage_result: Any) -> Any:
    if not isinstance(stage_result, dict):
        return None
    issues = stage_result.get("blocking_issues")
    if isinstance(issues, list) and issues:
        return issues[0]
    return None


def _storage_execution_diagnostics(stages: dict[str, Any]) -> dict[str, Any]:
    if stages.get("storage_reuse"):
        return {
            "storage_execution_attempted": False,
            "create_object_attempted": False,
            "upload_object_attempted": False,
            "verify_object_attempted": False,
            "create_object_result": None,
            "upload_object_result": None,
            "verify_object_result": stages.get("storage_verification"),
            "storage_execution_blocking_issue": _stage_blocking_issue(stages.get("storage_state_persistence")),
        }
    create_result = stages.get("storage_create")
    upload_result = stages.get("storage_upload")
    verify_result = stages.get("storage_verification")
    blocking_issue = (
        _stage_blocking_issue(create_result)
        or _stage_blocking_issue(upload_result)
        or _stage_blocking_issue(verify_result)
        or _stage_blocking_issue(stages.get("storage_state_persistence"))
    )
    return {
        "storage_execution_attempted": any(
            stage in stages for stage in ("storage_create", "storage_upload", "storage_verification")
        ),
        "create_object_attempted": "storage_create" in stages,
        "upload_object_attempted": "storage_upload" in stages,
        "verify_object_attempted": "storage_verification" in stages,
        "create_object_result": create_result,
        "upload_object_result": upload_result,
        "verify_object_result": verify_result,
        "storage_execution_blocking_issue": blocking_issue,
    }


def _content_request_metadata(
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    object_handle: dict[str, Any],
    content: bytes,
    content_sha256: str,
) -> dict[str, Any]:
    metadata = {
        "object_handle": object_handle,
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "content_bytes": base64.b64encode(content).decode("ascii"),
        "checksum": content_sha256,
        "content_length": len(content),
        "size_bytes": len(content),
        "lifecycle_metadata": dict(payload.lifecycle_metadata or {}),
    }
    return metadata


def _object_handle_from(status: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [status.get("object_handle")]
    for key in ("execution_request", "result_descriptor", "verification_descriptor", "latest_storage_verification"):
        candidate = status.get(key) if isinstance(status.get(key), dict) else {}
        candidates.append(candidate.get("object_handle"))
        operation_result = (
            candidate.get("storage_operation_result")
            if isinstance(candidate.get("storage_operation_result"), dict)
            else {}
        )
        candidates.append(operation_result.get("object_handle"))
        metadata = operation_result.get("metadata") if isinstance(operation_result.get("metadata"), dict) else {}
        candidates.append(metadata.get("object_handle"))
    for value in candidates:
        if isinstance(value, dict) and value:
            return value
    return None


def _verified_storage_status(
    *, verification: dict[str, Any], upload_status: dict[str, Any], object_handle: dict[str, Any]
) -> dict[str, Any]:
    if verification.get("storage_verified"):
        return verification
    result_descriptor = (
        verification.get("result_descriptor") if isinstance(verification.get("result_descriptor"), dict) else {}
    )
    upload_descriptor = (
        upload_status.get("result_descriptor") if isinstance(upload_status.get("result_descriptor"), dict) else {}
    )
    execution_request = (
        verification.get("execution_request") if isinstance(verification.get("execution_request"), dict) else {}
    )
    verification_descriptor = (
        verification.get("verification_descriptor")
        if isinstance(verification.get("verification_descriptor"), dict)
        else {}
    )
    evidence = {
        "object_exists": bool(result_descriptor.get("object_exists") or upload_descriptor.get("object_exists")),
        "object_stored": bool(result_descriptor.get("object_stored") or upload_descriptor.get("object_stored")),
        "file_uploaded": bool(result_descriptor.get("file_uploaded") or upload_descriptor.get("file_uploaded")),
        "checksum_calculated": bool(
            result_descriptor.get("checksum_calculated") or upload_descriptor.get("checksum_calculated")
        ),
        "checksum": result_descriptor.get("checksum") or upload_descriptor.get("checksum"),
        "content_length": _first_not_none(
            result_descriptor.get("content_length"), upload_descriptor.get("content_length")
        ),
        "content_type": result_descriptor.get("content_type") or upload_descriptor.get("content_type"),
    }
    verified = (
        evidence["object_exists"]
        and evidence["object_stored"]
        and evidence["file_uploaded"]
        and evidence["checksum_calculated"]
        and bool(evidence["checksum"])
        and isinstance(evidence["content_length"], int)
        and evidence["content_length"] >= 0
    )
    if not verified:
        return verification
    return {
        **verification,
        "storage_verified": True,
        "storage_verification_status": "storage_verified",
        "storage_verification_available": True,
        "processing_handoff_prerequisite_met": True,
        "blocking_issues": [],
        "object_exists": True,
        "object_stored": True,
        "file_uploaded": True,
        "checksum_calculated": True,
        "checksum": evidence["checksum"],
        "content_length": evidence["content_length"],
        "content_type": evidence["content_type"],
        "object_handle": object_handle,
        "execution_request": {
            **execution_request,
            "storage_verified": True,
            "storage_verification_status": "storage_verified",
            "storage_verification_available": True,
            "blocking_issues": [],
            "object_exists": True,
            "object_stored": True,
            "file_uploaded": True,
            "checksum_calculated": True,
            "checksum": evidence["checksum"],
            "content_length": evidence["content_length"],
            "content_type": evidence["content_type"],
            "object_handle": object_handle,
        },
        "verification_descriptor": {
            **verification_descriptor,
            "verification_status": "storage_verified",
            "storage_verified": True,
            "verification_available": True,
            "object_exists": True,
            "object_stored": True,
            "file_uploaded": True,
            "checksum_calculated": True,
            "checksum": evidence["checksum"],
            "content_length": evidence["content_length"],
            "content_type": evidence["content_type"],
            "object_handle": object_handle,
        },
        "result_descriptor": {
            **result_descriptor,
            "result_status": "storage_verified",
            "blocking_issues": [],
            "object_exists": True,
            "object_stored": True,
            "file_uploaded": True,
            "checksum_calculated": True,
            "checksum": evidence["checksum"],
            "content_length": evidence["content_length"],
            "content_type": evidence["content_type"],
            "object_handle": object_handle,
        },
    }


def _storage_status_with_lifecycle_lineage(
    storage_status: dict[str, Any],
    *,
    artifact_id: str,
    document_record_id: str,
    document_version_id: str,
) -> dict[str, Any]:
    status = dict(storage_status or {})
    lineage = {
        "artifact_id": str(artifact_id),
        "document_record_id": str(document_record_id),
        "document_version_id": str(document_version_id),
    }
    status.update(lineage)
    for nested_key in (
        "execution_request",
        "result_descriptor",
        "verification_descriptor",
        "storage_execution_session",
        "upload_session",
    ):
        nested = status.get(nested_key)
        if isinstance(nested, dict):
            status[nested_key] = {**nested, **lineage}
    execution_request = status.get("execution_request")
    if isinstance(execution_request, dict):
        for nested_key in ("storage_execution_session", "upload_session"):
            nested = execution_request.get(nested_key)
            if isinstance(nested, dict):
                execution_request[nested_key] = {**nested, **lineage}
        status["execution_request"] = execution_request
    return status


def build_document_lifecycle_orchestration(
    db: Session,
    *,
    payload: DocumentLifecycleOrchestrateRequest,
    actor_permissions: frozenset[str],
) -> dict[str, Any]:
    content, content_issues = _content_bytes(payload)
    content_sha256 = _content_sha256(content)
    lifecycle_key, lifecycle_key_source = _lifecycle_idempotency_key(payload, content_sha256)
    stages: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    strict_runtime = _strict_runtime_required(payload)
    if content_issues:
        return _block_response(
            payload=payload,
            lifecycle_key=lifecycle_key,
            lifecycle_key_source=lifecycle_key_source,
            blocking_issues=content_issues,
            stages=stages,
        )
    file_content = content or b""
    file_checksum_sha256 = content_sha256 or _content_sha256(file_content) or ""
    file_size_bytes = payload.size_bytes if payload.size_bytes is not None else len(file_content)
    registration = build_document_registration_execution(
        db,
        payload=payload.registration,
        commit=False,
    )
    stages["document_registration"] = registration
    warnings.extend(registration.get("warnings") or [])
    if registration.get("blocking_issues"):
        return _block_response(
            payload=payload,
            lifecycle_key=lifecycle_key,
            lifecycle_key_source=lifecycle_key_source,
            blocking_issues=registration.get("blocking_issues") or [],
            warnings=warnings,
            stages=stages,
        )
    document_record_id = registration.get("document_record_id")
    if not document_record_id:
        return _block_response(
            payload=payload,
            lifecycle_key=lifecycle_key,
            lifecycle_key_source=lifecycle_key_source,
            blocking_issues=[
                _issue(
                    "document_record_id_missing",
                    "Document registration did not return document_record_id.",
                    component="document_registration",
                )
            ],
            warnings=warnings,
            stages=stages,
        )
    document_record = db.get(DocumentRecord, uuid.UUID(str(document_record_id)))
    if document_record is None:
        db.rollback()
        return _block_response(
            payload=payload,
            lifecycle_key=lifecycle_key,
            lifecycle_key_source=lifecycle_key_source,
            blocking_issues=[
                _issue(
                    "document_record_not_available_for_association",
                    "Document registration was not available for organization association.",
                    component="document_organization_association",
                )
            ],
            warnings=warnings,
            stages=stages,
        )
    association_result = DocumentOrganizationAssociationService(
        db,
        organization_id=payload.registration.organization_id,
        actor_reference=(
            payload.requested_by
            or payload.registration.requested_by
            or "document-lifecycle"
        ),
        actor_permissions=actor_permissions,
    ).apply_initial(
        document_record,
        organization_node_ids=payload.organization_node_ids,
        mutation_key=lifecycle_key,
        document_created=bool(registration.get("document_record_created")),
    )
    stages["document_organization_associations"] = association_result
    db.commit()

    version = _create_or_get_document_version(
        db,
        payload=payload,
        document_record_id=str(document_record_id),
        lifecycle_key=lifecycle_key,
        content_sha256=content_sha256,
        size_bytes=file_size_bytes,
    )
    stages["document_version"] = version
    warnings.extend(version.get("warnings") or [])
    if version.get("blocking_issues"):
        return _block_response(
            payload=payload,
            lifecycle_key=lifecycle_key,
            lifecycle_key_source=lifecycle_key_source,
            blocking_issues=version.get("blocking_issues") or [],
            warnings=warnings,
            stages=stages,
        )
    document_version_id = version.get("document_version_id")

    storage_reused = False
    existing_version_record = (
        db.get(DocumentVersion, uuid.UUID(str(document_version_id))) if document_version_id else None
    )
    if _version_storage_verified(existing_version_record):
        existing_artifact = _existing_artifact_for_document_version(db, document_version_id=str(document_version_id))
        if existing_artifact is None:
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=[
                    _issue(
                        "existing_storage_artifact_missing",
                        "DocumentVersion has verified storage metadata but no associated Artifact was found.",
                        component="document_lifecycle",
                        item_id=str(document_version_id),
                    )
                ],
                warnings=warnings,
                stages=stages,
            )
        storage_reused = True
        artifact_id = str(existing_artifact.id)
        verification = _reconstructed_storage_status_from_persisted_state(
            artifact=existing_artifact,
            version=existing_version_record,
        )
        verification = _storage_status_with_lifecycle_lineage(
            verification,
            artifact_id=artifact_id,
            document_record_id=str(document_record_id),
            document_version_id=str(document_version_id),
        )
        storage_reuse_issues = _storage_reuse_contract_issues(verification)
        processing_handoff = build_document_processing_handoff(
            artifact_id=artifact_id,
            storage_execution_status=verification,
        )
        stages["processing_handoff_diagnostics"] = {
            "storage_reused": True,
            "storage_reuse_status_reconstructed": True,
            "storage_reuse_status_complete": not bool(storage_reuse_issues),
            "processing_handoff_ready": bool(processing_handoff.get("processing_handoff_ready")),
            "processing_handoff_blocking_issues": processing_handoff.get("handoff_blocking_issues") or [],
            "blocking_issues": [*storage_reuse_issues, *(processing_handoff.get("handoff_blocking_issues") or [])],
            "warnings": processing_handoff.get("handoff_warnings") or [],
            "processing_handoff": processing_handoff,
        }
        if storage_reuse_issues or not processing_handoff.get("processing_handoff_ready"):
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=[*storage_reuse_issues, *(processing_handoff.get("handoff_blocking_issues") or [])],
                warnings=warnings + (processing_handoff.get("handoff_warnings") or []),
                stages=stages,
            )
        persisted_storage = _persisted_storage_state_response(
            artifact=existing_artifact,
            version=existing_version_record,
        )
        stages["storage_reuse"] = {
            "storage_reused": True,
            "artifact_id": artifact_id,
            "document_version_id": str(document_version_id),
            "storage_verified": True,
            "blocking_issues": [],
            "warnings": [],
        }
        stages["storage_verification"] = verification
        stages["storage_state_persistence"] = persisted_storage
    else:
        upload = build_document_binary_upload_execution(
            db,
            payload=DocumentBinaryUploadExecuteRequest(
                organization_id=payload.registration.organization_id,
                document_record_id=uuid.UUID(str(document_record_id)),
                document_version_id=uuid.UUID(str(document_version_id)),
                file_name=payload.file_name,
                content_type=payload.content_type,
                size_bytes=file_size_bytes,
                metadata={
                    **dict(payload.lifecycle_metadata or {}),
                    "storage_provider": _storage_provider_config(payload),
                    "document_lifecycle_orchestrator": True,
                    "document_lifecycle_idempotency_key": lifecycle_key,
                },
                requested_by=payload.requested_by or payload.registration.requested_by,
                idempotency_key=f"{lifecycle_key}:binary-upload",
            ),
        )
        stages["document_binary_upload"] = upload
        warnings.extend(upload.get("warnings") or [])
        if upload.get("blocking_issues"):
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=upload.get("blocking_issues") or [],
                warnings=warnings,
                stages=stages,
            )
        artifact_id = upload.get("artifact_id")

        create_status = build_storage_execution_request_status(
            db,
            artifact_id=uuid.UUID(str(artifact_id)),
            requested_operation="create_object",
            requested_by=payload.requested_by or payload.registration.requested_by,
            request_metadata={"file_name": payload.file_name, "content_type": payload.content_type},
            idempotency_key=f"{lifecycle_key}:storage-create",
        )
        stages["storage_create"] = create_status
        object_handle = _object_handle_from(create_status or {})
        if not create_status or create_status.get("blocking_issues") or object_handle is None:
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=(create_status or {}).get("blocking_issues")
                or [
                    _issue(
                        "storage_create_failed",
                        "Storage create operation did not return an object_handle.",
                        component="storage",
                    )
                ],
                warnings=warnings + ((create_status or {}).get("warnings") or []),
                stages=stages,
            )

        upload_status = build_storage_execution_request_status(
            db,
            artifact_id=uuid.UUID(str(artifact_id)),
            requested_operation="upload_object",
            requested_by=payload.requested_by or payload.registration.requested_by,
            request_metadata=_content_request_metadata(
                payload=payload,
                object_handle=object_handle,
                content=file_content,
                content_sha256=file_checksum_sha256,
            ),
            idempotency_key=f"{lifecycle_key}:storage-upload",
        )
        stages["storage_upload"] = upload_status
        object_handle = _object_handle_from(upload_status or {}) or object_handle
        upload_descriptor = (
            (upload_status or {}).get("result_descriptor")
            if isinstance((upload_status or {}).get("result_descriptor"), dict)
            else {}
        )
        upload_completed = bool(
            upload_status
            and not upload_status.get("blocking_issues")
            and upload_descriptor.get("file_uploaded")
            and upload_descriptor.get("object_stored")
            and upload_descriptor.get("checksum_calculated")
            and upload_descriptor.get("checksum")
            and isinstance(upload_descriptor.get("content_length"), int)
            and upload_descriptor.get("content_length") == len(file_content)
        )
        if not upload_status or upload_status.get("blocking_issues") or not upload_completed:
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=(upload_status or {}).get("blocking_issues")
                or [_issue("storage_upload_failed", "Storage upload operation failed.", component="storage")],
                warnings=warnings + ((upload_status or {}).get("warnings") or []),
                stages=stages,
            )

        verification = build_storage_execution_request_status(
            db,
            artifact_id=uuid.UUID(str(artifact_id)),
            requested_operation="verify_object",
            requested_by=payload.requested_by or payload.registration.requested_by,
            request_metadata={
                "object_handle": object_handle,
                "file_name": payload.file_name,
                "content_type": payload.content_type,
                "checksum": file_checksum_sha256,
                "content_length": len(file_content),
                "size_bytes": len(file_content),
            },
            idempotency_key=f"{lifecycle_key}:storage-verify",
        )
        verification = _verified_storage_status(
            verification=verification or {},
            upload_status=upload_status,
            object_handle=_object_handle_from(verification or {}) or object_handle,
        )
        verification = _storage_status_with_lifecycle_lineage(
            verification,
            artifact_id=str(artifact_id),
            document_record_id=str(document_record_id),
            document_version_id=str(document_version_id),
        )
        stages["storage_verification"] = verification
        warnings.extend((verification or {}).get("warnings") or [])
        if not verification or verification.get("blocking_issues") or not verification.get("storage_verified"):
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=(verification or {}).get("blocking_issues")
                or [
                    _issue("storage_verification_failed", "Storage verification did not complete.", component="storage")
                ],
                warnings=warnings,
                stages=stages,
            )

        persisted_storage = _persist_storage_state(
            db,
            artifact_id=str(artifact_id),
            document_version_id=str(document_version_id),
            verification=verification,
        )
        stages["storage_state_persistence"] = persisted_storage
        if persisted_storage.get("blocking_issues"):
            return _block_response(
                payload=payload,
                lifecycle_key=lifecycle_key,
                lifecycle_key_source=lifecycle_key_source,
                blocking_issues=persisted_storage.get("blocking_issues") or [],
                warnings=warnings,
                stages=stages,
            )

    processing_exception_issue: dict[str, Any] | None = None
    processing_runtime_execution: dict[str, Any] = {}
    try:
        processing_publication_search, processing_runtime_execution, runtime_execution_issues = (
            _processing_publication_search_with_runtime_execution(
                db,
                payload=payload,
                lifecycle_key=lifecycle_key,
                artifact_id=str(artifact_id),
                document_record_id=str(document_record_id),
                document_version_id=str(document_version_id),
                verification=verification,
            )
        )
        if runtime_execution_issues:
            processing_publication_search = {
                "processing_publication_search_status": "failed" if strict_runtime else "pending",
                "processing_completed": False,
                "chunks_created": False,
                "knowledge_published": False,
                "index_succeeded": False,
                "search_succeeded": False,
                "blocking_issues": runtime_execution_issues,
                "warnings": [],
                "runtime_execution": processing_runtime_execution,
            }
    except Exception as exc:
        processing_exception_issue = _issue(
            "processing_publication_search_failed",
            str(exc),
            component="processing_publication_search",
            item_id=exc.__class__.__name__,
        )
        processing_publication_search = {
            "processing_publication_search_status": "failed" if strict_runtime else "pending",
            "processing_completed": False,
            "chunks_created": False,
            "knowledge_published": False,
            "index_succeeded": False,
            "search_succeeded": False,
            "blocking_issues": [processing_exception_issue],
            "warnings": [],
            "runtime_execution": processing_runtime_execution,
        }
    if isinstance(processing_publication_search, dict):
        processing_publication_search["runtime_execution"] = processing_runtime_execution
    stages["processing_publication_search"] = processing_publication_search
    if processing_publication_search is None:
        processing_publication_search = {
            "processing_publication_search_status": "failed" if strict_runtime else "pending",
            "processing_completed": False,
            "chunks_created": False,
            "knowledge_published": False,
            "index_succeeded": False,
            "search_succeeded": False,
            "blocking_issues": [
                _issue(
                    "processing_publication_search_missing",
                    "Processing/publication/search execution returned no result.",
                    component="processing_publication_search",
                )
            ]
            if strict_runtime
            else [],
            "warnings": []
            if strict_runtime
            else [
                _warning(
                    "worker_runtime_pending",
                    "Processing/publication/search execution is pending after storage verification.",
                    component="worker_runtime",
                )
            ],
        }
        stages["processing_publication_search"] = processing_publication_search

    strict_runtime_issues = (
        _processing_publication_search_issues(processing_publication_search) if strict_runtime else []
    )
    knowledge_index_summary = _knowledge_index_summary(processing_publication_search)
    enterprise_search_summary = _enterprise_search_summary(processing_publication_search, knowledge_index_summary)
    knowledge_indexed = bool(knowledge_index_summary.get("knowledge_indexed"))
    enterprise_search_ready = bool(enterprise_search_summary.get("enterprise_search_ready"))
    processing_handoff_diagnostics = (
        stages.get("processing_handoff_diagnostics")
        if isinstance(stages.get("processing_handoff_diagnostics"), dict)
        else {}
    )
    _persist_lifecycle_completion_state(
        db,
        document_version_id=str(document_version_id),
        processing_publication_search=processing_publication_search,
        storage_reused=storage_reused,
        storage_reuse_status_complete=bool(
            processing_handoff_diagnostics.get("storage_reuse_status_complete", not storage_reused)
        ),
        processing_handoff_ready=bool(processing_handoff_diagnostics.get("processing_handoff_ready", True)),
        processing_handoff_blocking_issues=processing_handoff_diagnostics.get("processing_handoff_blocking_issues")
        or [],
    )

    orchestration_prepared = bool(
        verification.get("storage_verified") and persisted_storage.get("storage_state_persisted")
    )
    lifecycle_completed = bool(
        registration.get("document_record_id")
        and document_version_id
        and verification.get("storage_verified")
        and _lifecycle_completed_from_processing(processing_publication_search)
    )
    worker_execution_completed = bool(
        registration.get("document_record_id")
        and document_version_id
        and verification.get("storage_verified")
        and _publication_index_completed_from_processing(processing_publication_search)
    )
    worker_lifecycle_status = _worker_lifecycle_status(
        db,
        organization_id=payload.registration.organization_id,
        document_version_id=str(document_version_id),
        orchestration_prepared=orchestration_prepared,
        lifecycle_completed=worker_execution_completed,
        processing_publication_search=processing_publication_search,
    )
    stage_issues: list[dict[str, Any]] = []
    stage_warnings: list[dict[str, Any]] = []
    for stage_name, result in stages.items():
        if isinstance(result, dict):
            for issue in result.get("blocking_issues") or []:
                if isinstance(issue, dict):
                    stage_issues.append({**issue, "stage": stage_name})
            for warning in result.get("warnings") or []:
                if isinstance(warning, dict):
                    stage_warnings.append({**warning, "stage": stage_name})
    if worker_lifecycle_status.get("runtime_execution_failed") and not worker_execution_completed:
        stage_issues.append(
            _issue(
                "worker_runtime_execution_failed",
                worker_lifecycle_status.get("runtime_execution_error_message")
                or "Asynchronous worker runtime execution failed.",
                component="worker_runtime",
                item_id=worker_lifecycle_status.get("runtime_execution_id"),
            )
        )
    if orchestration_prepared and not worker_lifecycle_status.get("runtime_execution_id"):
        stage_issues.append(
            _issue(
                "PROCESSING_RUNTIME_EXECUTION_MISSING",
                "Document lifecycle requires a persisted runtime_execution_id after storage verification.",
                component="worker_runtime",
            )
        )
    worker_execution_pending = bool(worker_lifecycle_status.get("worker_execution_pending"))
    knowledge_publication_pending = orchestration_prepared and not bool(
        processing_publication_search.get("knowledge_published")
    )
    enterprise_search_pending = orchestration_prepared and not enterprise_search_ready
    if worker_execution_pending and not strict_runtime and not worker_lifecycle_status.get("runtime_execution_failed"):
        stage_warnings.append(
            _warning(
                "worker_runtime_pending",
                "Document storage is verified and ready for asynchronous worker execution.",
                component="worker_runtime",
            )
        )
    storage_diagnostics = _storage_execution_diagnostics(stages)
    response_blocking_issues = _sort_issues([*stage_issues, *strict_runtime_issues])
    response_warnings = _sort_issues([*warnings, *stage_warnings])
    hard_runtime_failure = bool(
        (
            worker_lifecycle_status.get("runtime_execution_failed")
            or (orchestration_prepared and not worker_lifecycle_status.get("runtime_execution_id"))
        )
        and not worker_execution_completed
    )
    response_passed = (
        lifecycle_completed if strict_runtime or hard_runtime_failure else lifecycle_completed or orchestration_prepared
    )
    response_status = (
        "completed"
        if lifecycle_completed
        else "blocked"
        if hard_runtime_failure
        else "blocked"
        if strict_runtime and response_blocking_issues
        else "prepared"
        if orchestration_prepared
        else "blocked"
    )
    processing_publication_search_status = (
        "completed"
        if lifecycle_completed
        else "blocked"
        if strict_runtime and strict_runtime_issues
        else processing_publication_search.get("processing_publication_search_status") or "pending"
    )
    knowledge_document_id = knowledge_index_summary.get("knowledge_document_id")
    knowledge_chunk_count = knowledge_index_summary.get("knowledge_chunk_count")
    response = {
        "document_lifecycle_orchestrator_schema_version": DOCUMENT_LIFECYCLE_ORCHESTRATOR_SCHEMA_VERSION,
        "lifecycle_status": response_status,
        "lifecycle_completed": lifecycle_completed,
        "orchestration_prepared": orchestration_prepared,
        "passed": response_passed,
        "strict_runtime_required": strict_runtime,
        "organization_id": str(payload.registration.organization_id),
        "document_record_id": str(document_record_id),
        "document_version_id": str(document_version_id),
        "artifact_id": str(artifact_id),
        "idempotency": {
            "key": lifecycle_key,
            "source": lifecycle_key_source,
        },
        "document_registered": bool(registration.get("document_record_id")),
        "document_version_ready": bool(document_version_id),
        "binary_uploaded": bool(verification.get("file_uploaded")),
        "binary_attached": bool(persisted_storage.get("binary_attached")),
        "upload_executed": bool(persisted_storage.get("upload_executed")),
        "file_uploaded": bool(persisted_storage.get("file_uploaded")),
        "storage_reused": bool(storage_reused),
        "storage_reuse_status_reconstructed": bool(storage_reused),
        "storage_reuse_status_complete": bool(
            processing_handoff_diagnostics.get("storage_reuse_status_complete", True)
        ),
        "storage_verified": bool(verification.get("storage_verified")),
        "object_store_provider": persisted_storage.get("object_store_provider"),
        "object_store_bucket": persisted_storage.get("object_store_bucket"),
        "object_store_key": persisted_storage.get("object_store_key") or persisted_storage.get("object_key"),
        "checksum_sha256": persisted_storage.get("checksum_sha256"),
        "size_bytes": persisted_storage.get("size_bytes"),
        "content_type": persisted_storage.get("content_type"),
        **storage_diagnostics,
        "processing_ready": bool(processing_publication_search.get("processing_completed")),
        "processing_completed": bool(processing_publication_search.get("processing_completed")),
        "chunks_created": bool(processing_publication_search.get("chunks_created")),
        "worker_runtime_ready": bool(worker_lifecycle_status.get("worker_runtime_ready")),
        "worker_required": bool(worker_lifecycle_status.get("worker_required")),
        "worker_execution_pending": bool(worker_execution_pending),
        "worker_execution_completed": bool(worker_execution_completed),
        "runtime_execution_id": worker_lifecycle_status.get("runtime_execution_id"),
        "runtime_execution_status": worker_lifecycle_status.get("runtime_execution_status"),
        "runtime_execution_type": worker_lifecycle_status.get("runtime_execution_type"),
        "worker_runtime_diagnostics": worker_lifecycle_status,
        "publication_ready": bool(persisted_storage.get("publication_ready")),
        "knowledge_published": bool(processing_publication_search.get("knowledge_published")),
        "knowledge_publication_pending": bool(knowledge_publication_pending),
        "knowledge_indexed": knowledge_indexed,
        "enterprise_search_visible": enterprise_search_ready,
        "enterprise_search_ready": enterprise_search_ready,
        "search_ready": enterprise_search_ready,
        "enterprise_search_pending": bool(enterprise_search_pending),
        "assistant_chat_available": enterprise_search_ready,
        "chat_ready": enterprise_search_ready,
        "knowledge_document_id": knowledge_document_id,
        "knowledge_document_ids": knowledge_index_summary.get("knowledge_document_ids") or [],
        "knowledge_chunk_count": knowledge_chunk_count,
        "knowledge_chunks_indexed": knowledge_index_summary.get("knowledge_chunks_indexed"),
        "knowledge_chunks_created": knowledge_index_summary.get("knowledge_chunks_created"),
        "knowledge_chunks_updated": knowledge_index_summary.get("knowledge_chunks_updated"),
        "knowledge_index_status": knowledge_index_summary.get("knowledge_index_status"),
        "knowledge_index_blocking_issues": knowledge_index_summary.get("knowledge_index_blocking_issues") or [],
        "knowledge_index_warnings": knowledge_index_summary.get("knowledge_index_warnings") or [],
        "search_result_count": enterprise_search_summary.get("search_result_count"),
        "search_index_contract_inconsistent": enterprise_search_summary.get("search_index_contract_inconsistent"),
        "processing_publication_search_status": processing_publication_search_status,
        "processing_publication_search_blocking_issues": _sort_issues(
            [*(processing_publication_search.get("blocking_issues") or []), *strict_runtime_issues]
        ),
        "processing_publication_search_warnings": processing_publication_search.get("warnings") or [],
        "processing_handoff_ready": bool(processing_handoff_diagnostics.get("processing_handoff_ready", True)),
        "processing_handoff_blocking_issues": processing_handoff_diagnostics.get("processing_handoff_blocking_issues")
        or [],
        "stages": stages,
        "blocking_issues": response_blocking_issues
        if strict_runtime or hard_runtime_failure or not orchestration_prepared
        else [],
        "warnings": response_warnings,
        "ai_required": False,
        "embeddings_required": False,
        "vector_store_required": False,
        "postgresql_source_of_truth": True,
    }
    response["runtime_persistence"] = processing_publication_search.get("runtime_persistence")
    return response
