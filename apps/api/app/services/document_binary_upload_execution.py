"""Metadata-only binary upload execution foundation for DocumentVersion placeholders."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.documents import Artifact, DocumentRecord, DocumentVersion
from app.schemas.documents import DocumentBinaryUploadExecuteRequest, DocumentBinaryUploadPlanRequest
from app.services.document_binary_upload_planning import build_document_binary_upload_plan
from app.services.document_binary_upload_session import (
    build_upload_session_from_artifact_data,
    build_upload_session_from_execution_context,
    serialize_upload_session,
)
from app.services.storage_provider_contracts import (
    STORAGE_OPERATION_GENERATE_UPLOAD,
    STORAGE_OPERATION_NONE,
    STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
    StorageProvider,
    sanitize_storage_provider_configuration,
)
from app.services.storage_provider_registry import get_storage_provider_registry
from app.services.storage_provider_runtime import get_storage_provider_runtime_adapter

DOCUMENT_BINARY_UPLOAD_EXECUTION_SCHEMA_VERSION = "1"
BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE = "binary_upload_placeholder"
BINARY_UPLOAD_INITIAL_STATUS = "upload_pending"
STORAGE_NOT_CONFIGURED_STATUS = STORAGE_PROVIDER_STATUS_NOT_CONFIGURED
EXECUTION_FALSE_FLAGS = {
    "file_uploaded": False,
    "object_stored": False,
    "checksum_calculated": False,
    "ingestion_executed": False,
    "chunks_created": False,
    "embeddings_created": False,
    "workflow_executed": False,
    "ai_required": False,
    "vector_store_required": False,
    "ai_vector_not_required": True,
    "destructive_action_executed": False,
    "migration_executed": False,
    "downgrade_executed": False,
}
STORAGE_DESCRIPTOR_FLAG_KEYS = {
    "file_uploaded",
    "object_stored",
    "checksum_calculated",
    "ingestion_executed",
    "chunks_created",
    "embeddings_created",
    "ai_required",
    "vector_store_required",
}
STORAGE_STATE_FLAG_KEYS = {
    "file_uploaded",
    "object_stored",
    "checksum_calculated",
}
STATUS_FLAG_KEYS = (
    "file_uploaded",
    "object_stored",
    "checksum_calculated",
    "ingestion_executed",
    "chunks_created",
    "embeddings_created",
    "ai_required",
    "vector_store_required",
)


def _issue(code: str, message: str, *, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _normalized_requested_by(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _source_metadata(payload: DocumentBinaryUploadExecuteRequest) -> dict[str, Any]:
    return sanitize_storage_provider_configuration(payload.metadata) if isinstance(payload.metadata, dict) else {}


def _normalized_file_name(payload: DocumentBinaryUploadExecuteRequest) -> str | None:
    if payload.file_name is None:
        return None
    normalized = payload.file_name.strip()
    return normalized or None


def _normalized_content_type(payload: DocumentBinaryUploadExecuteRequest) -> str | None:
    if payload.content_type is None:
        return None
    normalized = payload.content_type.strip()
    return normalized or None


def _contract_validation_issues(payload: DocumentBinaryUploadExecuteRequest) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if payload.document_version_id is None:
        issues.append(
            _issue(
                "document_version_id_required",
                "Binary upload execution requires document_version_id.",
                component="document_version",
            )
        )
    if not _normalized_file_name(payload):
        issues.append(
            _issue(
                "file_name_required",
                "Binary upload execution requires file_name.",
                component="binary_upload",
            )
        )
    if not _normalized_content_type(payload):
        issues.append(
            _issue(
                "content_type_required",
                "Binary upload execution requires content_type.",
                component="binary_upload",
            )
        )
    if payload.size_bytes is None or payload.size_bytes <= 0:
        issues.append(
            _issue(
                "size_bytes_must_be_positive",
                "Binary upload execution requires size_bytes greater than zero.",
                component="binary_upload",
                item_id=str(payload.size_bytes),
            )
        )
    if not isinstance(payload.metadata, dict):
        issues.append(
            _issue(
                "source_metadata_must_be_object",
                "Binary upload source metadata must be an object.",
                component="binary_upload",
            )
        )
    return issues


def _execution_flag_subset(source: dict[str, Any], keys: set[str] | tuple[str, ...]) -> dict[str, bool]:
    return {key: bool(source.get(key)) for key in keys}


def _storage_operation_state(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **_execution_flag_subset(source, STORAGE_STATE_FLAG_KEYS),
        "object_handle": source.get("object_handle"),
    }


def _resolved_idempotency_key(payload: DocumentBinaryUploadExecuteRequest) -> tuple[str, str]:
    if payload.idempotency_key:
        normalized_key = payload.idempotency_key.strip()
        if normalized_key:
            return normalized_key, "client_supplied"
    identity = {
        "organization_id": str(payload.organization_id),
        "document_record_id": str(payload.document_record_id),
        "document_version_id": str(payload.document_version_id),
        "file_name": _normalized_file_name(payload),
        "content_type": _normalized_content_type(payload),
        "size_bytes": payload.size_bytes,
        "metadata": _source_metadata(payload),
    }
    digest = hashlib.sha256(_stable_json(identity).encode("utf-8")).hexdigest()
    return f"document-binary-upload:{digest}", "derived_from_upload_descriptor"


def _provider_resolution_trace_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    provider_name = str(metadata.get("storage_provider_name") or "null")
    provider_type = str(metadata.get("storage_provider_type") or "null")
    return {
        "requested_provider_name": metadata.get("requested_provider_name"),
        "resolved_provider_name": provider_name,
        "resolved_provider_type": provider_type,
        "provider_configured": bool(metadata.get("storage_provider_configured")),
        "provider_status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        "registry_fallback_used": provider_name == "null",
        "provider_operation_invoked": False,
        "storage_operation": metadata.get("storage_operation") or STORAGE_OPERATION_NONE,
    }


def _future_storage_descriptor_from_metadata(artifact: Artifact, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "descriptor_schema_version": "1",
        "descriptor_type": "document_binary_upload",
        "organization_id": str(artifact.organization_id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(artifact.document_version_id),
        "artifact_type": artifact.artifact_type,
        "file_name": metadata.get("file_name"),
        "content_type": metadata.get("content_type"),
        "mime_type": metadata.get("mime_type") or metadata.get("content_type"),
        "size_bytes": metadata.get("size_bytes", artifact.size_bytes),
        "source_metadata": metadata.get("source_metadata") if isinstance(metadata.get("source_metadata"), dict) else {},
        "requested_by": _normalized_requested_by(metadata.get("requested_by")),
        "storage_provider_name": metadata.get("storage_provider_name") or "null",
        "storage_provider_type": metadata.get("storage_provider_type") or "null",
        "storage_provider_configured": bool(metadata.get("storage_provider_configured")),
        "storage_provider_status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        "storage_backend_binding": {},
        "storage_operation": metadata.get("storage_operation") or STORAGE_OPERATION_NONE,
        "object_handle": metadata.get("object_handle"),
        **_execution_flag_subset(metadata, STORAGE_DESCRIPTOR_FLAG_KEYS),
    }


def build_storage_operation_plan(
    *,
    storage_provider: StorageProvider,
    storage_descriptor: dict[str, Any],
    provider_resolution_trace: dict[str, Any],
) -> dict[str, Any]:
    """Plan future storage execution without invoking a storage provider."""

    provider_descriptor = storage_provider.descriptor
    runtime_trace = get_storage_provider_runtime_adapter().build_runtime_trace(
        storage_provider=storage_provider,
        storage_descriptor=storage_descriptor,
        requested_operation=STORAGE_OPERATION_GENERATE_UPLOAD,
        execute=False,
    )
    capability = provider_descriptor.capability(STORAGE_OPERATION_GENERATE_UPLOAD)
    provider_is_null = provider_descriptor.provider_type == "null" or provider_descriptor.provider_name == "null"
    storage_ready = runtime_trace["runtime_state"] == "future_ready"
    storage_execution_allowed = bool(runtime_trace["execution_allowed"])
    required_next_step = runtime_trace["required_next_step"]
    provider_status = runtime_trace["missing_configuration_reason"] or runtime_trace["provider_status"]
    operation_request = runtime_trace["operation_request"]
    operation_result = runtime_trace["operation_result"]
    return {
        "storage_operation_plan_schema_version": "1",
        "planned_operation": "generate_upload",
        "operation_invoked": runtime_trace["operation_invoked"],
        "storage_ready": storage_ready,
        "storage_execution_allowed": storage_execution_allowed,
        "required_next_step": required_next_step,
        "provider_validation": {
            "provider_name": storage_provider.provider_name,
            "provider_type": storage_provider.provider_type,
            "provider_configured": storage_provider.configured,
            "provider_is_null": provider_is_null,
            "status": provider_status,
            "capability": capability.as_dict(),
        },
        "storage_provider_name": storage_provider.provider_name,
        "storage_provider_type": storage_provider.provider_type,
        "storage_provider_configured": storage_provider.configured,
        "storage_provider_status": provider_status,
        "storage_operation": STORAGE_OPERATION_NONE,
        "provider_descriptor": provider_descriptor.as_dict(),
        "capabilities": runtime_trace["capabilities"],
        "operation_request": operation_request,
        "operation_result": operation_result,
        "runtime_trace": runtime_trace,
        "runtime_state": runtime_trace["runtime_state"],
        "missing_configuration_reason": runtime_trace["missing_configuration_reason"],
        "planning": {
            "operation": STORAGE_OPERATION_GENERATE_UPLOAD,
            "storage_ready": storage_ready,
            "required_next_step": required_next_step,
        },
        "execution": {
            "allowed": storage_execution_allowed,
            "invoked": False,
            "reason": None if storage_execution_allowed else provider_status,
        },
        "result": operation_result,
        "state": {
            "file_uploaded": False,
            "object_stored": False,
            "checksum_calculated": False,
            "object_handle": None,
        },
        "prepared_operations": runtime_trace["operations"],
        "object_handle": None,
        "file_uploaded": False,
        "object_stored": False,
        "checksum_calculated": False,
        "provider_resolution_trace": provider_resolution_trace,
        "future_storage_descriptor": storage_descriptor,
    }


def _storage_operation_plan_from_metadata(artifact: Artifact, metadata: dict[str, Any]) -> dict[str, Any]:
    existing = metadata.get("storage_operation_plan")
    descriptor = (
        metadata.get("future_storage_descriptor")
        if isinstance(metadata.get("future_storage_descriptor"), dict)
        else _future_storage_descriptor_from_metadata(artifact, metadata)
    )
    trace = (
        metadata.get("provider_resolution_trace")
        if isinstance(metadata.get("provider_resolution_trace"), dict)
        else _provider_resolution_trace_from_metadata(metadata)
    )
    provider_descriptor = {
        "provider_name": metadata.get("storage_provider_name") or "null",
        "provider_type": metadata.get("storage_provider_type") or "null",
        "configured": bool(metadata.get("storage_provider_configured")),
        "status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        "capabilities": [],
        "metadata": {},
    }
    operation_request = {
        "operation": STORAGE_OPERATION_GENERATE_UPLOAD,
        "provider": provider_descriptor,
        "object_handle": None,
        "descriptor": descriptor,
        "metadata": {"stage": "binary_upload_execution"},
        "requested_by": descriptor.get("requested_by"),
        "payload_included": False,
    }
    operation_result = {
        "operation": STORAGE_OPERATION_GENERATE_UPLOAD,
        "status": STORAGE_NOT_CONFIGURED_STATUS,
        "provider": provider_descriptor,
        "executed": False,
        "storage_ready": False,
        "object_handle": None,
        "metadata": {
            "requested_by": descriptor.get("requested_by"),
            "descriptor": descriptor,
            "operation_request": operation_request,
        },
        "required_next_step": "configure_storage_provider",
    }
    runtime_trace = (
        metadata.get("runtime_trace")
        if isinstance(metadata.get("runtime_trace"), dict)
        else {
            "storage_runtime_trace_schema_version": "1",
            "requested_operation": STORAGE_OPERATION_GENERATE_UPLOAD,
            "runtime_state": "not_configured",
            "execution_prepared": True,
            "execution_allowed": False,
            "operation_invoked": False,
            "provider_name": provider_descriptor["provider_name"],
            "provider_type": provider_descriptor["provider_type"],
            "provider_configured": provider_descriptor["configured"],
            "provider_status": provider_descriptor["status"],
            "provider_descriptor": provider_descriptor,
            "capabilities": provider_descriptor["capabilities"],
            "missing_configuration_reason": STORAGE_NOT_CONFIGURED_STATUS,
            "required_next_step": "configure_storage_provider",
            "operation_request": operation_request,
            "operation_result": operation_result,
            "operations": {
                STORAGE_OPERATION_GENERATE_UPLOAD: operation_request,
            },
            "state_model": {
                "requested": "requested",
                "planned": "planned",
                "blocked": "blocked",
                "skipped": "skipped",
                "not_configured": "not_configured",
                "future_ready": "future_ready",
            },
        }
    )
    state = _storage_operation_state(metadata)
    fallback_plan = {
        "storage_operation_plan_schema_version": "1",
        "planned_operation": "generate_upload",
        "operation_invoked": False,
        "storage_ready": False,
        "storage_execution_allowed": False,
        "required_next_step": "configure_storage_provider",
        "provider_validation": {
            "provider_name": metadata.get("storage_provider_name") or "null",
            "provider_type": metadata.get("storage_provider_type") or "null",
            "provider_configured": bool(metadata.get("storage_provider_configured")),
            "provider_is_null": (metadata.get("storage_provider_name") or "null") == "null",
            "status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        },
        "storage_provider_name": metadata.get("storage_provider_name") or "null",
        "storage_provider_type": metadata.get("storage_provider_type") or "null",
        "storage_provider_configured": bool(metadata.get("storage_provider_configured")),
        "storage_provider_status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        "storage_operation": metadata.get("storage_operation") or STORAGE_OPERATION_NONE,
        "object_handle": metadata.get("object_handle"),
        "file_uploaded": state["file_uploaded"],
        "object_stored": state["object_stored"],
        "checksum_calculated": state["checksum_calculated"],
        "provider_descriptor": provider_descriptor,
        "capabilities": provider_descriptor["capabilities"],
        "operation_request": operation_request,
        "operation_result": operation_result,
        "runtime_trace": runtime_trace,
        "runtime_state": runtime_trace["runtime_state"],
        "missing_configuration_reason": runtime_trace["missing_configuration_reason"],
        "planning": {
            "operation": STORAGE_OPERATION_GENERATE_UPLOAD,
            "storage_ready": False,
            "required_next_step": "configure_storage_provider",
        },
        "execution": {
            "allowed": False,
            "invoked": False,
            "reason": STORAGE_NOT_CONFIGURED_STATUS,
        },
        "result": operation_result,
        "state": state,
        "prepared_operations": runtime_trace["operations"],
        "provider_resolution_trace": trace,
        "future_storage_descriptor": descriptor,
    }
    if isinstance(existing, dict):
        normalized_existing = {
            **fallback_plan,
            **existing,
        }
        normalized_existing["runtime_trace"] = existing.get("runtime_trace") or runtime_trace
        normalized_existing["runtime_state"] = existing.get("runtime_state") or runtime_trace["runtime_state"]
        normalized_existing["missing_configuration_reason"] = (
            existing.get("missing_configuration_reason") or runtime_trace["missing_configuration_reason"]
        )
        normalized_existing["required_next_step"] = (
            existing.get("required_next_step") or fallback_plan["required_next_step"]
        )
        normalized_existing["provider_descriptor"] = existing.get("provider_descriptor") or provider_descriptor
        normalized_existing["capabilities"] = existing.get("capabilities") or provider_descriptor["capabilities"]
        normalized_existing["operation_result"] = existing.get("operation_result") or operation_result
        normalized_existing["operation_request"] = existing.get("operation_request") or operation_request
        normalized_existing["prepared_operations"] = existing.get("prepared_operations") or runtime_trace["operations"]
        return normalized_existing
    return fallback_plan


def _artifact_placeholder_metadata(artifact: Artifact) -> dict[str, Any]:
    metadata = artifact.metadata_json or {}
    future_storage_descriptor = (
        metadata.get("future_storage_descriptor")
        if isinstance(metadata.get("future_storage_descriptor"), dict)
        else _future_storage_descriptor_from_metadata(artifact, metadata)
    )
    provider_resolution_trace = (
        metadata.get("provider_resolution_trace")
        if isinstance(metadata.get("provider_resolution_trace"), dict)
        else _provider_resolution_trace_from_metadata(metadata)
    )
    storage_operation_plan = _storage_operation_plan_from_metadata(artifact, metadata)
    runtime_trace = (
        metadata.get("runtime_trace")
        if isinstance(metadata.get("runtime_trace"), dict)
        else storage_operation_plan.get("runtime_trace")
    )
    configuration_readiness = (
        metadata.get("storage_configuration_readiness")
        if isinstance(metadata.get("storage_configuration_readiness"), dict)
        else (
            future_storage_descriptor.get("storage_configuration_readiness")
            if isinstance(future_storage_descriptor, dict)
            else None
        )
        or {
            "configured": bool(metadata.get("storage_provider_configured")),
            "status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
            "missing_configuration_reason": storage_operation_plan.get("missing_configuration_reason"),
            "required_configuration_keys": [],
            "safe_configuration_fingerprint": None,
        }
    )
    return {
        "idempotency_key": metadata.get("idempotency_key"),
        "idempotency_key_source": metadata.get("idempotency_key_source"),
        "file_name": metadata.get("file_name"),
        "content_type": metadata.get("content_type"),
        "mime_type": metadata.get("mime_type") or metadata.get("content_type"),
        "size_bytes": metadata.get("size_bytes"),
        "upload_status": metadata.get("upload_status") or artifact.status,
        "source_metadata": metadata.get("source_metadata") if isinstance(metadata.get("source_metadata"), dict) else {},
        "requested_by": _normalized_requested_by(metadata.get("requested_by")),
        "storage_provider_name": metadata.get("storage_provider_name") or "null",
        "storage_provider_type": metadata.get("storage_provider_type") or "null",
        "storage_provider_configured": bool(metadata.get("storage_provider_configured")),
        "storage_provider_status": metadata.get("storage_provider_status") or STORAGE_NOT_CONFIGURED_STATUS,
        "storage_operation": metadata.get("storage_operation") or STORAGE_OPERATION_NONE,
        "object_handle": metadata.get("object_handle"),
        **_execution_flag_subset(metadata, STATUS_FLAG_KEYS),
        "future_storage_descriptor": future_storage_descriptor,
        "provider_resolution_trace": provider_resolution_trace,
        "storage_operation_plan": storage_operation_plan,
        "runtime_trace": runtime_trace,
        "runtime_state": storage_operation_plan.get("runtime_state") or (runtime_trace or {}).get("runtime_state"),
        "storage_operation_result": storage_operation_plan.get("operation_result"),
        "provider_descriptor": storage_operation_plan.get("provider_descriptor"),
        "capabilities": storage_operation_plan.get("capabilities") or [],
        "storage_configuration_readiness": configuration_readiness,
        "missing_configuration_reason": storage_operation_plan.get("missing_configuration_reason"),
        "required_next_step": storage_operation_plan.get("required_next_step"),
    }


def _read_artifact(artifact: Artifact) -> dict[str, Any]:
    placeholder = _artifact_placeholder_metadata(artifact)
    return {
        "id": str(artifact.id),
        "organization_id": str(artifact.organization_id),
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(artifact.document_version_id),
        "artifact_type": artifact.artifact_type,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "status": artifact.status,
        "file_name": placeholder["file_name"],
        "requested_by": placeholder["requested_by"],
        "source_metadata": placeholder["source_metadata"],
        "storage_provider_name": placeholder["storage_provider_name"],
        "storage_provider_configured": placeholder["storage_provider_configured"],
        "storage_provider_type": placeholder["storage_provider_type"],
        "storage_provider_status": placeholder["storage_provider_status"],
        "storage_operation": placeholder["storage_operation"],
        "object_handle": placeholder["object_handle"],
        "file_uploaded": placeholder["file_uploaded"],
        "object_stored": placeholder["object_stored"],
        "checksum_calculated": placeholder["checksum_calculated"],
        "ingestion_executed": placeholder["ingestion_executed"],
        "chunks_created": placeholder["chunks_created"],
        "embeddings_created": placeholder["embeddings_created"],
        "ai_required": placeholder["ai_required"],
        "vector_store_required": placeholder["vector_store_required"],
        "future_storage_descriptor": placeholder["future_storage_descriptor"],
        "provider_resolution_trace": placeholder["provider_resolution_trace"],
        "storage_operation_plan": placeholder["storage_operation_plan"],
        "runtime_trace": placeholder["runtime_trace"],
        "runtime_state": placeholder["runtime_state"],
        "storage_operation_result": placeholder["storage_operation_result"],
        "provider_descriptor": placeholder["provider_descriptor"],
        "capabilities": placeholder["capabilities"],
        "storage_configuration_readiness": placeholder["storage_configuration_readiness"],
        "missing_configuration_reason": placeholder["missing_configuration_reason"],
        "required_next_step": placeholder["required_next_step"],
        "artifact_placeholder_metadata": placeholder,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
        "created_by": artifact.created_by,
        "updated_by": artifact.updated_by,
    }


def _document_record(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_record_id: uuid.UUID,
) -> DocumentRecord | None:
    return db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.organization_id == organization_id,
            DocumentRecord.id == document_record_id,
        )
    )


def _document_version(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_record_id: uuid.UUID,
    document_version_id: uuid.UUID,
    for_update: bool = False,
) -> DocumentVersion | None:
    statement = select(DocumentVersion).where(
        DocumentVersion.organization_id == organization_id,
        DocumentVersion.document_record_id == document_record_id,
        DocumentVersion.id == document_version_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _existing_artifact_by_idempotency_key(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_record_id: uuid.UUID,
    document_version_id: uuid.UUID,
    idempotency_key: str,
) -> Artifact | None:
    statement = (
        select(Artifact)
        .where(
            Artifact.organization_id == organization_id,
            Artifact.document_record_id == document_record_id,
            Artifact.document_version_id == document_version_id,
            Artifact.artifact_type == BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
            Artifact.metadata_json["idempotency_key"].astext == idempotency_key,
        )
        .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        .limit(1)
    )
    return db.scalars(statement).first()


def _existing_artifact_for_version(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_record_id: uuid.UUID,
    document_version_id: uuid.UUID,
) -> Artifact | None:
    statement = (
        select(Artifact)
        .where(
            Artifact.organization_id == organization_id,
            Artifact.document_record_id == document_record_id,
            Artifact.document_version_id == document_version_id,
            Artifact.artifact_type == BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
        )
        .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        .limit(1)
    )
    return db.scalars(statement).first()


def _binary_upload_artifact_by_id(db: Session, *, artifact_id: uuid.UUID) -> Artifact | None:
    statement = select(Artifact).where(
        Artifact.id == artifact_id,
        Artifact.artifact_type == BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
    )
    return db.scalar(statement)


def _base_response(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    execution_status: str,
    idempotency_key: str,
    idempotency_key_source: str,
) -> dict[str, Any]:
    return {
        "plan": "document_binary_upload_execution",
        "document_binary_upload_execution_schema_version": DOCUMENT_BINARY_UPLOAD_EXECUTION_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "document_record_id": str(payload.document_record_id),
        "document_version_id": str(payload.document_version_id),
        "execution_status": execution_status,
        "idempotency": {
            "mode": "artifact_metadata",
            "idempotency_key": idempotency_key,
            "idempotency_key_source": idempotency_key_source,
            "idempotency_key_present": bool(payload.idempotency_key),
        },
    }


def _next_available_actions(*, placeholder_available: bool) -> list[dict[str, Any]]:
    return [
        {
            "action": "attach_binary_content",
            "available": placeholder_available,
            "executed": False,
            "status": "ready" if placeholder_available else "not_available",
            "reason": "storage_provider_execution_is_future_capability",
        },
        {
            "action": "calculate_checksum",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "binary_content_not_uploaded",
        },
        {
            "action": "schedule_ingestion",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "ingestion_is_future_capability",
        },
    ]


def _upload_session_next_available_actions(
    upload_session_payload: dict[str, Any] | None,
    *,
    placeholder_available: bool,
) -> list[dict[str, Any]]:
    if upload_session_payload:
        return upload_session_payload.get("next_available_actions") or []
    return _next_available_actions(placeholder_available=placeholder_available)


def _execution_flags(
    created: bool,
    *,
    storage_provider: StorageProvider | None = None,
    storage_operation: str = "none",
) -> dict[str, Any]:
    provider_name = storage_provider.provider_name if storage_provider else "null"
    provider_type = storage_provider.provider_type if storage_provider else "null"
    provider_configured = storage_provider.configured if storage_provider else False
    provider_status = storage_provider.descriptor.status if storage_provider else STORAGE_NOT_CONFIGURED_STATUS
    return {
        "upload_record_created": created,
        "object_handle": None,
        "storage_provider_name": provider_name,
        "storage_provider_configured": provider_configured,
        "storage_provider_type": provider_type,
        "storage_provider_status": provider_status,
        "storage_operation": storage_operation,
        **EXECUTION_FALSE_FLAGS,
    }


def _execution_flags_from_storage_plan(
    storage_operation_plan: dict[str, Any],
    *,
    created: bool,
    storage_provider: StorageProvider | None = None,
    storage_operation: str = STORAGE_OPERATION_NONE,
) -> dict[str, Any]:
    flags = _execution_flags(
        created,
        storage_provider=storage_provider,
        storage_operation=storage_operation,
    )
    for key in (
        "storage_provider_name",
        "storage_provider_type",
        "storage_provider_configured",
        "storage_provider_status",
        "storage_operation",
        "object_handle",
        "file_uploaded",
        "object_stored",
        "checksum_calculated",
    ):
        if key in storage_operation_plan:
            flags[key] = storage_operation_plan[key]
    return flags


def _execution_flags_from_artifact(artifact: Artifact, *, created: bool) -> dict[str, Any]:
    metadata = artifact.metadata_json or {}
    flags = _execution_flags(created)
    for key in (
        *STATUS_FLAG_KEYS,
        "object_handle",
        "storage_provider_name",
        "storage_provider_configured",
        "storage_provider_type",
        "storage_provider_status",
        "storage_operation",
    ):
        if key in metadata:
            flags[key] = metadata[key]
    return flags


def _storage_metadata_from_flags(flags: dict[str, Any]) -> dict[str, Any]:
    return {
        "storage_provider_name": flags["storage_provider_name"],
        "storage_provider_type": flags["storage_provider_type"],
        "storage_provider_configured": flags["storage_provider_configured"],
        "storage_provider_status": flags["storage_provider_status"],
        "storage_operation": flags["storage_operation"],
        "object_handle": flags["object_handle"],
        "object_stored": flags["object_stored"],
        "file_uploaded": flags["file_uploaded"],
        "checksum_calculated": flags["checksum_calculated"],
    }


def _build_final_response(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    execution_status: str,
    plan: dict[str, Any],
    idempotency_key: str,
    idempotency_key_source: str,
    idempotency_status: str,
    artifact: Artifact | None,
    upload_record_created: bool,
    idempotent_replay: bool,
    placeholder_available: bool,
    blocking_issues: list[dict[str, Any]],
    warnings: list[dict[str, Any]] | None = None,
    storage_provider: StorageProvider | None = None,
    storage_descriptor: dict[str, Any] | None = None,
    provider_resolution_trace: dict[str, Any] | None = None,
    storage_operation_plan: dict[str, Any] | None = None,
    generated_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _base_response(
        payload,
        execution_status=execution_status,
        idempotency_key=idempotency_key,
        idempotency_key_source=idempotency_key_source,
    )
    artifact_data = _read_artifact(artifact) if artifact is not None else None
    flags = (
        _execution_flags_from_artifact(artifact, created=upload_record_created)
        if artifact is not None
        else _execution_flags(upload_record_created, storage_provider=storage_provider)
    )
    effective_storage_descriptor = storage_descriptor
    effective_provider_trace = provider_resolution_trace
    effective_storage_operation_plan = storage_operation_plan
    effective_runtime_trace = (storage_operation_plan or {}).get("runtime_trace") if storage_operation_plan else None
    artifact_placeholder_metadata = None
    upload_session_payload = None
    if artifact_data is not None:
        artifact_placeholder_metadata = artifact_data["artifact_placeholder_metadata"]
        effective_storage_descriptor = (
            artifact_placeholder_metadata.get("future_storage_descriptor") or storage_descriptor
        )
        effective_provider_trace = (
            artifact_placeholder_metadata.get("provider_resolution_trace") or provider_resolution_trace
        )
        effective_storage_operation_plan = (
            artifact_placeholder_metadata.get("storage_operation_plan") or storage_operation_plan
        )
        effective_runtime_trace = artifact_placeholder_metadata.get("runtime_trace") or effective_runtime_trace
        upload_session_payload = serialize_upload_session(
            build_upload_session_from_artifact_data(
                artifact_data,
                upload_record_created=upload_record_created,
            )
        )
    else:
        upload_session_payload = serialize_upload_session(
            build_upload_session_from_execution_context(
                artifact_id=None,
                document_record_id=str(payload.document_record_id) if payload.document_record_id else None,
                document_version_id=str(payload.document_version_id) if payload.document_version_id else None,
                storage_operation_plan=effective_storage_operation_plan,
                runtime_trace=effective_runtime_trace,
                provider_descriptor=(effective_storage_operation_plan or {}).get("provider_descriptor"),
                execution_flags=flags,
                storage_configuration_readiness=(
                    (effective_storage_descriptor or {}).get("storage_configuration_readiness")
                    if isinstance(effective_storage_descriptor, dict)
                    else None
                ),
                placeholder_available=placeholder_available,
            )
        )

    response.update(
        {
            "artifact_id": str(artifact.id) if artifact is not None else None,
            "binary_upload_id": str(artifact.id) if artifact is not None else None,
            "upload_artifact": artifact_data,
            "upload_session": upload_session_payload,
            "upload_session_id": upload_session_payload.get("upload_session_id") if upload_session_payload else None,
            "artifact_placeholder_metadata": artifact_placeholder_metadata,
            "storage_metadata": _storage_metadata_from_flags(upload_session_payload.get("execution_flags") or flags),
            "future_storage_descriptor": effective_storage_descriptor,
            "provider_resolution_trace": effective_provider_trace,
            "storage_operation_plan": upload_session_payload.get("storage_operation_plan"),
            "runtime_trace": upload_session_payload.get("runtime_trace"),
            "runtime_state": upload_session_payload.get("runtime_state"),
            "storage_operation_result": upload_session_payload.get("storage_operation_result"),
            "provider_descriptor": upload_session_payload.get("storage_provider_descriptor"),
            "capabilities": (upload_session_payload.get("storage_provider_descriptor") or {}).get("capabilities") or [],
            "storage_configuration_readiness": upload_session_payload.get("storage_configuration_readiness"),
            "missing_configuration_reason": (upload_session_payload.get("storage_operation_plan") or {}).get(
                "missing_configuration_reason"
            ),
            "required_next_step": (upload_session_payload.get("storage_operation_plan") or {}).get(
                "required_next_step"
            ),
            "idempotent_replay": idempotent_replay,
            "next_available_actions": _upload_session_next_available_actions(
                upload_session_payload,
                placeholder_available=placeholder_available,
            ),
            "blocking_issues": _sort_issues(blocking_issues),
            "warnings": warnings or [],
            "plan_input": plan,
            "generated_from": generated_from or {"document_binary_upload_plan": plan.get("plan")},
            **(upload_session_payload.get("execution_flags") or flags),
        }
    )
    response["idempotency"]["status"] = idempotency_status
    response["idempotency"]["idempotent_replay"] = idempotent_replay
    response["idempotency"]["existing_artifact_id"] = (
        str(artifact.id) if artifact is not None and idempotent_replay else None
    )
    return response


def _blocked(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    idempotency_key: str,
    idempotency_key_source: str,
    plan: dict[str, Any],
    issues: list[dict[str, Any]],
    idempotency_status: str = "conflict_blocked",
    storage_provider: StorageProvider | None = None,
    storage_descriptor: dict[str, Any] | None = None,
    provider_resolution_trace: dict[str, Any] | None = None,
    storage_operation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _build_final_response(
        payload,
        execution_status="blocked",
        plan=plan,
        idempotency_key=idempotency_key,
        idempotency_key_source=idempotency_key_source,
        idempotency_status=idempotency_status,
        artifact=None,
        upload_record_created=False,
        idempotent_replay=False,
        placeholder_available=False,
        blocking_issues=list(plan.get("blocking_issues") or []) + issues,
        warnings=plan.get("warnings") or [],
        storage_provider=storage_provider,
        storage_descriptor=storage_descriptor,
        provider_resolution_trace=provider_resolution_trace,
        storage_operation_plan=storage_operation_plan,
        generated_from={"document_binary_upload_plan": plan.get("plan")},
    )


def _already_executed(
    payload: DocumentBinaryUploadExecuteRequest,
    artifact: Artifact,
    *,
    idempotency_key: str,
    idempotency_key_source: str,
    plan: dict[str, Any] | None = None,
    status: str = "already_executed",
) -> dict[str, Any]:
    response = _build_final_response(
        payload,
        execution_status=status,
        plan=plan or {},
        idempotency_key=idempotency_key,
        idempotency_key_source=idempotency_key_source,
        idempotency_status="replayed",
        artifact=artifact,
        upload_record_created=False,
        idempotent_replay=True,
        placeholder_available=True,
        blocking_issues=[],
        warnings=(plan or {}).get("warnings") or [],
        generated_from={"idempotency_lookup": "documents.artifacts.metadata.idempotency_key"},
    )
    response["idempotency"]["existing_artifact_id"] = str(artifact.id)
    return response


def _normalized_storage_provider_name(plan: dict[str, Any]) -> str | None:
    binding = plan.get("storage_backend_binding") or {}
    selected = binding.get("selected") if isinstance(binding, dict) else None
    if isinstance(selected, str):
        candidate = selected
    elif isinstance(selected, dict):
        candidate = None
        for key in ("provider_name", "provider", "name", "type"):
            value = selected.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value
                break
    else:
        candidate = None

    if not isinstance(candidate, str):
        return None
    normalized = candidate.strip().lower()
    return normalized or None


def _storage_provider_configuration_from_selection(selection: Any) -> dict[str, Any]:
    if not isinstance(selection, dict):
        return {}
    candidate = selection.get("configuration") if isinstance(selection.get("configuration"), dict) else selection
    configuration = dict(candidate)
    provider_name = configuration.get("provider_name") or configuration.get("provider") or configuration.get("name")
    provider_type = configuration.get("provider_type") or configuration.get("type")
    if provider_name:
        configuration["provider_name"] = provider_name
    if provider_type:
        configuration["provider_type"] = provider_type
    return configuration


def _storage_provider_selection(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    plan: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    plan_binding = plan.get("storage_backend_binding") if isinstance(plan.get("storage_backend_binding"), dict) else {}
    source_metadata = _source_metadata(payload)
    metadata_binding = (
        source_metadata.get("storage_backend_binding")
        if isinstance(source_metadata.get("storage_backend_binding"), dict)
        else {}
    )
    metadata_provider = (
        source_metadata.get("storage_provider")
        if isinstance(source_metadata.get("storage_provider"), dict)
        else source_metadata.get("storage_provider_configuration")
        if isinstance(source_metadata.get("storage_provider_configuration"), dict)
        else {}
    )
    selected = metadata_binding.get("selected", plan_binding.get("selected"))
    configuration = _storage_provider_configuration_from_selection(selected)
    if not configuration and isinstance(metadata_provider, dict):
        configuration = _storage_provider_configuration_from_selection(metadata_provider)
    provider_name = _normalized_storage_provider_name({"storage_backend_binding": {"selected": selected}})
    if provider_name is None and configuration:
        configured_name = (
            configuration.get("provider_name") or configuration.get("name") or configuration.get("provider")
        )
        provider_name = str(configured_name).strip().lower() if configured_name else "configurable"
    if provider_name is None:
        provider_name = _normalized_storage_provider_name(plan)
    return provider_name, configuration


def _provider_resolution_trace(
    *,
    requested_provider_name: str | None,
    storage_provider: StorageProvider,
    registry_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_descriptor = storage_provider.descriptor
    trace = {
        "requested_provider_name": requested_provider_name,
        "resolved_provider_name": storage_provider.provider_name,
        "resolved_provider_type": storage_provider.provider_type,
        "provider_configured": storage_provider.configured,
        "provider_status": provider_descriptor.status,
        "provider_descriptor": provider_descriptor.as_dict(),
        "registry_fallback_used": requested_provider_name is None
        or requested_provider_name != storage_provider.provider_name,
        "provider_operation_invoked": False,
        "storage_operation": STORAGE_OPERATION_NONE,
    }
    if registry_trace:
        trace["registry_resolution"] = registry_trace
        trace["registry_fallback_used"] = bool(registry_trace.get("registry_fallback_used"))
    return trace


def _build_future_storage_descriptor(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    plan: dict[str, Any],
    storage_provider: StorageProvider,
) -> dict[str, Any]:
    provider_descriptor = storage_provider.descriptor
    return {
        "descriptor_schema_version": "1",
        "descriptor_type": "document_binary_upload",
        "organization_id": str(payload.organization_id),
        "document_record_id": str(payload.document_record_id),
        "document_version_id": str(payload.document_version_id),
        "artifact_type": BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
        "file_name": _normalized_file_name(payload),
        "content_type": _normalized_content_type(payload),
        "mime_type": _normalized_content_type(payload),
        "size_bytes": payload.size_bytes,
        "source_metadata": _source_metadata(payload),
        "requested_by": _normalized_requested_by(payload.requested_by),
        "storage_provider_name": storage_provider.provider_name,
        "storage_provider_type": storage_provider.provider_type,
        "storage_provider_configured": storage_provider.configured,
        "storage_provider_status": provider_descriptor.status,
        "storage_provider_descriptor": provider_descriptor.as_dict(),
        "storage_configuration_readiness": {
            "configured": provider_descriptor.configured,
            "status": provider_descriptor.status,
            "missing_configuration_reason": provider_descriptor.missing_configuration_reason,
            "required_configuration_keys": list(provider_descriptor.required_configuration_keys),
            "safe_configuration_fingerprint": provider_descriptor.safe_configuration_fingerprint,
        },
        "storage_backend_binding": plan.get("storage_backend_binding") or {},
        "storage_operation": STORAGE_OPERATION_NONE,
        "object_handle": None,
        **{key: value for key, value in EXECUTION_FALSE_FLAGS.items() if key in STORAGE_DESCRIPTOR_FLAG_KEYS},
    }


def _build_placeholder_metadata(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    idempotency_key: str,
    idempotency_key_source: str,
    storage_provider: StorageProvider,
    storage_descriptor: dict[str, Any],
    provider_resolution_trace: dict[str, Any],
    storage_operation_plan: dict[str, Any],
    storage_operation: str,
) -> dict[str, Any]:
    flags = _execution_flags_from_storage_plan(
        storage_operation_plan,
        created=False,
        storage_provider=storage_provider,
        storage_operation=storage_operation,
    )
    return {
        "idempotency_key": idempotency_key,
        "idempotency_key_source": idempotency_key_source,
        "file_name": _normalized_file_name(payload),
        "content_type": _normalized_content_type(payload),
        "mime_type": _normalized_content_type(payload),
        "size_bytes": payload.size_bytes,
        "upload_status": BINARY_UPLOAD_INITIAL_STATUS,
        "source_metadata": _source_metadata(payload),
        "requested_by": _normalized_requested_by(payload.requested_by),
        "future_storage_descriptor": storage_descriptor,
        "provider_resolution_trace": provider_resolution_trace,
        "storage_operation_plan": storage_operation_plan,
        "runtime_trace": storage_operation_plan.get("runtime_trace"),
        "storage_configuration_readiness": storage_descriptor.get("storage_configuration_readiness"),
        "storage_provider_selected": storage_provider.provider_name != "null",
        **{key: value for key, value in flags.items() if key != "upload_record_created"},
    }


def _new_artifact(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    idempotency_key: str,
    idempotency_key_source: str,
    storage_provider: StorageProvider,
    storage_descriptor: dict[str, Any],
    provider_resolution_trace: dict[str, Any],
    storage_operation_plan: dict[str, Any],
    storage_operation: str,
) -> Artifact:
    artifact = Artifact(
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        ingestion_job_id=None,
        artifact_type=BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
        media_type=_normalized_content_type(payload),
        object_store_provider=None,
        bucket=None,
        object_key=None,
        checksum_sha256=None,
        size_bytes=payload.size_bytes,
        metadata_json=_build_placeholder_metadata(
            payload,
            idempotency_key=idempotency_key,
            idempotency_key_source=idempotency_key_source,
            storage_provider=storage_provider,
            storage_descriptor=storage_descriptor,
            provider_resolution_trace=provider_resolution_trace,
            storage_operation_plan=storage_operation_plan,
            storage_operation=storage_operation,
        ),
        status=BINARY_UPLOAD_INITIAL_STATUS,
    )
    requested_by = _normalized_requested_by(payload.requested_by)
    if requested_by:
        artifact.created_by = requested_by
        artifact.updated_by = requested_by
    return artifact


def _build_plan_payload(payload: DocumentBinaryUploadExecuteRequest) -> DocumentBinaryUploadPlanRequest:
    return DocumentBinaryUploadPlanRequest(
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        file_name=_normalized_file_name(payload),
        content_type=_normalized_content_type(payload),
        size_bytes=payload.size_bytes,
        metadata=_source_metadata(payload),
    )


def _resolve_storage_readiness(
    payload: DocumentBinaryUploadExecuteRequest,
    *,
    plan: dict[str, Any],
) -> tuple[StorageProvider, dict[str, Any], dict[str, Any], dict[str, Any]]:
    requested_provider_name, provider_configuration = _storage_provider_selection(payload, plan=plan)
    storage_provider, registry_trace = get_storage_provider_registry().resolve_with_trace(
        requested_provider_name,
        configuration=provider_configuration,
    )
    provider_trace = _provider_resolution_trace(
        requested_provider_name=requested_provider_name,
        storage_provider=storage_provider,
        registry_trace=registry_trace,
    )
    storage_descriptor = _build_future_storage_descriptor(
        payload,
        plan=plan,
        storage_provider=storage_provider,
    )
    storage_operation_plan = build_storage_operation_plan(
        storage_provider=storage_provider,
        storage_descriptor=storage_descriptor,
        provider_resolution_trace=provider_trace,
    )
    provider_trace = storage_operation_plan.get("provider_resolution_trace") or provider_trace
    storage_descriptor = storage_operation_plan.get("future_storage_descriptor") or storage_descriptor
    return storage_provider, provider_trace, storage_descriptor, storage_operation_plan


def build_document_binary_upload_execution(
    db: Session,
    *,
    payload: DocumentBinaryUploadExecuteRequest,
) -> dict[str, Any]:
    """Create a persistent upload placeholder only; no binary content is stored."""

    idempotency_key, idempotency_key_source = _resolved_idempotency_key(payload)
    existing = _existing_artifact_by_idempotency_key(
        db,
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        return _already_executed(
            payload,
            existing,
            idempotency_key=idempotency_key,
            idempotency_key_source=idempotency_key_source,
        )

    version = _document_version(
        db,
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        for_update=True,
    )
    existing_for_version = _existing_artifact_for_version(
        db,
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
    )
    if existing_for_version is not None:
        plan = build_document_binary_upload_plan(db, payload=_build_plan_payload(payload))
        existing_metadata = existing_for_version.metadata_json or {}
        if existing_metadata.get("idempotency_key") == idempotency_key:
            return _already_executed(
                payload,
                existing_for_version,
                idempotency_key=idempotency_key,
                idempotency_key_source=idempotency_key_source,
                plan=plan,
                status="already_executed_after_race",
            )
        storage_provider, provider_resolution_trace, storage_descriptor, storage_operation_plan = (
            _resolve_storage_readiness(
                payload,
                plan=plan,
            )
        )
        return _blocked(
            payload,
            idempotency_key=idempotency_key,
            idempotency_key_source=idempotency_key_source,
            plan=plan,
            issues=[
                _issue(
                    "binary_upload_placeholder_already_exists",
                    "DocumentVersion already has a binary upload placeholder with a different idempotency key.",
                    component="binary_upload",
                    item_id=str(existing_for_version.id),
                )
            ],
            storage_provider=storage_provider,
            storage_descriptor=storage_descriptor,
            provider_resolution_trace=provider_resolution_trace,
            storage_operation_plan=storage_operation_plan,
        )

    plan = build_document_binary_upload_plan(db, payload=_build_plan_payload(payload))
    storage_provider, provider_resolution_trace, storage_descriptor, storage_operation_plan = (
        _resolve_storage_readiness(
            payload,
            plan=plan,
        )
    )
    storage_operation = STORAGE_OPERATION_NONE
    execution_issues: list[dict[str, Any]] = _contract_validation_issues(payload)

    record = _document_record(
        db,
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
    )
    if record is None:
        execution_issues.append(
            _issue(
                "document_record_not_found_for_execution",
                "DocumentRecord does not exist for the requested organization.",
                component="document_record",
                item_id=str(payload.document_record_id),
            )
        )

    if version is None:
        execution_issues.append(
            _issue(
                "document_version_not_found_for_execution",
                "DocumentVersion does not exist for the requested document and organization.",
                component="document_version",
                item_id=str(payload.document_version_id),
            )
        )

    if not plan.get("upload_allowed"):
        execution_issues.append(
            _issue(
                "binary_upload_plan_not_allowed",
                "Document binary upload execution is blocked by the upload plan.",
                component="binary_upload",
                item_id=str(payload.document_version_id),
            )
        )

    if execution_issues:
        return _blocked(
            payload,
            idempotency_key=idempotency_key,
            idempotency_key_source=idempotency_key_source,
            plan=plan,
            issues=execution_issues,
            storage_provider=storage_provider,
            storage_descriptor=storage_descriptor,
            provider_resolution_trace=provider_resolution_trace,
            storage_operation_plan=storage_operation_plan,
        )

    artifact = _new_artifact(
        payload,
        idempotency_key=idempotency_key,
        idempotency_key_source=idempotency_key_source,
        storage_provider=storage_provider,
        storage_descriptor=storage_descriptor,
        provider_resolution_trace=provider_resolution_trace,
        storage_operation_plan=storage_operation_plan,
        storage_operation=storage_operation,
    )
    db.add(artifact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_race = _existing_artifact_by_idempotency_key(
            db,
            organization_id=payload.organization_id,
            document_record_id=payload.document_record_id,
            document_version_id=payload.document_version_id,
            idempotency_key=idempotency_key,
        )
        if existing_after_race is not None:
            return _already_executed(
                payload,
                existing_after_race,
                idempotency_key=idempotency_key,
                idempotency_key_source=idempotency_key_source,
                plan=plan,
                status="already_executed_after_race",
            )
        raise

    db.refresh(artifact)
    response = _build_final_response(
        payload,
        execution_status="executed",
        plan=plan,
        idempotency_key=idempotency_key,
        idempotency_key_source=idempotency_key_source,
        idempotency_status="created",
        artifact=artifact,
        upload_record_created=True,
        idempotent_replay=False,
        placeholder_available=True,
        blocking_issues=[],
        warnings=plan.get("warnings") or [],
        storage_provider=storage_provider,
        storage_descriptor=storage_descriptor,
        provider_resolution_trace=provider_resolution_trace,
        storage_operation_plan=storage_operation_plan,
        generated_from={
            "document_binary_upload_plan": plan.get("plan"),
            "artifact_model": "documents.artifacts",
            "storage_provider_registry": "default_storage_provider_registry",
        },
    )
    response["idempotency"]["existing_artifact_id"] = None
    return response


def build_document_binary_upload_status(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    from app.services.document_binary_upload_control_plane import build_upload_session_status

    return build_upload_session_status(db, artifact_id=artifact_id)
