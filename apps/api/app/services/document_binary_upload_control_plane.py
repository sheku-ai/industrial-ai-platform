"""Control-plane services for binary upload sessions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.services.document_binary_upload_session import (
    UPLOAD_SESSION_FLAG_KEYS,
    build_upload_session_from_artifact_data,
    serialize_upload_session,
)
from app.services.document_processing_session import (
    build_processing_session,
    serialize_processing_session,
)
from app.services.storage_execution_gateway import (
    build_prepared_storage_execution,
)

BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE = "binary_upload_placeholder"


def _issue(
    code: str,
    message: str,
    *,
    component: str,
    severity: str = "blocking",
    item_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _binary_upload_artifact_by_id(db: Session, *, artifact_id: uuid.UUID) -> Artifact | None:
    statement = select(Artifact).where(
        Artifact.id == artifact_id,
        Artifact.artifact_type == BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE,
    )
    return db.scalar(statement)


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
        "requested_by": metadata.get("requested_by"),
        "storage_provider_name": metadata.get("storage_provider_name") or "null",
        "storage_provider_type": metadata.get("storage_provider_type") or "null",
        "storage_provider_configured": bool(metadata.get("storage_provider_configured")),
        "storage_provider_status": metadata.get("storage_provider_status") or "storage_not_configured",
        "storage_backend_binding": {},
        "storage_operation": metadata.get("storage_operation") or "none",
        "object_handle": metadata.get("object_handle"),
        "checksum": metadata.get("checksum"),
        "content_length": metadata.get("content_length"),
        "file_uploaded": bool(metadata.get("file_uploaded")),
        "object_stored": bool(metadata.get("object_stored")),
        "checksum_calculated": bool(metadata.get("checksum_calculated")),
        "storage_verified": bool(metadata.get("storage_verified")),
        "ingestion_executed": bool(metadata.get("ingestion_executed")),
        "chunks_created": bool(metadata.get("chunks_created")),
        "embeddings_created": bool(metadata.get("embeddings_created")),
        "ai_required": bool(metadata.get("ai_required")),
        "vector_store_required": bool(metadata.get("vector_store_required")),
    }


def _fallback_runtime_trace(metadata: dict[str, Any], storage_operation_plan: dict[str, Any]) -> dict[str, Any]:
    if isinstance(metadata.get("runtime_trace"), dict):
        return metadata["runtime_trace"]
    if isinstance(storage_operation_plan.get("runtime_trace"), dict):
        return storage_operation_plan["runtime_trace"]
    provider_descriptor = storage_operation_plan.get("provider_descriptor") or {
        "provider_name": metadata.get("storage_provider_name") or "null",
        "provider_type": metadata.get("storage_provider_type") or "null",
        "configured": bool(metadata.get("storage_provider_configured")),
        "status": metadata.get("storage_provider_status") or "storage_not_configured",
        "capabilities": [],
        "metadata": {},
    }
    operation_result = storage_operation_plan.get("operation_result") or {}
    return {
        "storage_runtime_trace_schema_version": "1",
        "requested_operation": storage_operation_plan.get("planned_operation") or "generate_upload",
        "runtime_state": storage_operation_plan.get("runtime_state") or "not_configured",
        "execution_prepared": True,
        "execution_allowed": bool(storage_operation_plan.get("storage_execution_allowed")),
        "operation_invoked": bool(storage_operation_plan.get("operation_invoked")),
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "provider_configured": bool(provider_descriptor.get("configured")),
        "provider_status": provider_descriptor.get("status"),
        "provider_descriptor": provider_descriptor,
        "capabilities": provider_descriptor.get("capabilities") or [],
        "missing_configuration_reason": storage_operation_plan.get("missing_configuration_reason"),
        "required_next_step": storage_operation_plan.get("required_next_step"),
        "operation_request": storage_operation_plan.get("operation_request") or {},
        "operation_result": operation_result,
        "operations": storage_operation_plan.get("prepared_operations") or {},
    }


def _fallback_storage_operation_plan(artifact: Artifact, metadata: dict[str, Any]) -> dict[str, Any]:
    existing = metadata.get("storage_operation_plan")
    if isinstance(existing, dict):
        return dict(existing)
    descriptor = (
        metadata.get("future_storage_descriptor")
        if isinstance(metadata.get("future_storage_descriptor"), dict)
        else _future_storage_descriptor_from_metadata(artifact, metadata)
    )
    provider_descriptor = {
        "provider_name": metadata.get("storage_provider_name") or "null",
        "provider_type": metadata.get("storage_provider_type") or "null",
        "configured": bool(metadata.get("storage_provider_configured")),
        "status": metadata.get("storage_provider_status") or "storage_not_configured",
        "capabilities": [],
        "metadata": {},
    }
    operation_request = {
        "operation": "generate_upload",
        "provider": provider_descriptor,
        "object_handle": None,
        "descriptor": descriptor,
        "metadata": {"stage": "binary_upload_execution"},
        "requested_by": descriptor.get("requested_by"),
        "payload_included": False,
    }
    operation_result = {
        "operation": "generate_upload",
        "status": "storage_not_configured",
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
    return {
        "storage_operation_plan_schema_version": "1",
        "planned_operation": "generate_upload",
        "operation_invoked": False,
        "storage_ready": False,
        "storage_execution_allowed": False,
        "required_next_step": "configure_storage_provider",
        "storage_provider_name": provider_descriptor["provider_name"],
        "storage_provider_type": provider_descriptor["provider_type"],
        "storage_provider_configured": provider_descriptor["configured"],
        "storage_provider_status": provider_descriptor["status"],
        "storage_operation": metadata.get("storage_operation") or "none",
        "provider_descriptor": provider_descriptor,
        "capabilities": provider_descriptor["capabilities"],
        "operation_request": operation_request,
        "operation_result": operation_result,
        "runtime_state": "not_configured",
        "missing_configuration_reason": "storage_not_configured",
        "prepared_operations": {"generate_upload": operation_request},
        "provider_resolution_trace": metadata.get("provider_resolution_trace")
        if isinstance(metadata.get("provider_resolution_trace"), dict)
        else {},
        "future_storage_descriptor": descriptor,
    }


def build_artifact_upload_session_data(artifact: Artifact) -> dict[str, Any]:
    metadata = artifact.metadata_json or {}
    storage_operation_plan = _fallback_storage_operation_plan(artifact, metadata)
    runtime_trace = _fallback_runtime_trace(metadata, storage_operation_plan)
    future_storage_descriptor = (
        metadata.get("future_storage_descriptor")
        if isinstance(metadata.get("future_storage_descriptor"), dict)
        else _future_storage_descriptor_from_metadata(artifact, metadata)
    )
    storage_configuration_readiness = (
        metadata.get("storage_configuration_readiness")
        if isinstance(metadata.get("storage_configuration_readiness"), dict)
        else future_storage_descriptor.get("storage_configuration_readiness")
        if isinstance(future_storage_descriptor, dict)
        else {}
    )
    placeholder = {
        "idempotency_key": metadata.get("idempotency_key"),
        "idempotency_key_source": metadata.get("idempotency_key_source"),
        "file_name": metadata.get("file_name"),
        "content_type": metadata.get("content_type"),
        "mime_type": metadata.get("mime_type") or metadata.get("content_type"),
        "size_bytes": metadata.get("size_bytes", artifact.size_bytes),
        "upload_status": metadata.get("upload_status") or artifact.status,
        "source_metadata": metadata.get("source_metadata") if isinstance(metadata.get("source_metadata"), dict) else {},
        "requested_by": metadata.get("requested_by"),
        "storage_provider_name": metadata.get("storage_provider_name") or "null",
        "storage_provider_type": metadata.get("storage_provider_type") or "null",
        "storage_provider_configured": bool(metadata.get("storage_provider_configured")),
        "storage_provider_status": metadata.get("storage_provider_status") or "storage_not_configured",
        "storage_operation": metadata.get("storage_operation") or "none",
        "object_handle": metadata.get("object_handle"),
        "checksum": metadata.get("checksum"),
        "content_length": metadata.get("content_length"),
        "file_uploaded": bool(metadata.get("file_uploaded")),
        "object_stored": bool(metadata.get("object_stored")),
        "checksum_calculated": bool(metadata.get("checksum_calculated")),
        "storage_verified": bool(metadata.get("storage_verified")),
        "ingestion_executed": bool(metadata.get("ingestion_executed")),
        "chunks_created": bool(metadata.get("chunks_created")),
        "embeddings_created": bool(metadata.get("embeddings_created")),
        "ai_required": bool(metadata.get("ai_required")),
        "vector_store_required": bool(metadata.get("vector_store_required")),
        "future_storage_descriptor": future_storage_descriptor,
        "provider_resolution_trace": metadata.get("provider_resolution_trace")
        if isinstance(metadata.get("provider_resolution_trace"), dict)
        else {},
        "storage_operation_plan": storage_operation_plan,
        "runtime_trace": runtime_trace,
        "runtime_state": storage_operation_plan.get("runtime_state") or runtime_trace.get("runtime_state"),
        "storage_operation_result": storage_operation_plan.get("operation_result")
        or runtime_trace.get("operation_result"),
        "provider_descriptor": storage_operation_plan.get("provider_descriptor")
        or runtime_trace.get("provider_descriptor"),
        "capabilities": storage_operation_plan.get("capabilities") or runtime_trace.get("capabilities") or [],
        "storage_configuration_readiness": storage_configuration_readiness,
        "missing_configuration_reason": storage_operation_plan.get("missing_configuration_reason")
        or runtime_trace.get("missing_configuration_reason"),
        "required_next_step": storage_operation_plan.get("required_next_step")
        or runtime_trace.get("required_next_step"),
    }
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
        "checksum": placeholder["checksum"],
        "content_length": placeholder["content_length"],
        "file_uploaded": placeholder["file_uploaded"],
        "object_stored": placeholder["object_stored"],
        "checksum_calculated": placeholder["checksum_calculated"],
        "storage_verified": placeholder["storage_verified"],
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


def validate_upload_session(
    *,
    artifact: Artifact,
    upload_artifact: dict[str, Any],
    upload_session: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    storage_operation_plan = upload_session.get("storage_operation_plan") or {}
    runtime_trace = upload_session.get("runtime_trace") or {}
    execution_flags = upload_session.get("execution_flags") or {}

    if upload_session.get("artifact_id") != str(artifact.id):
        blocking_issues.append(
            _issue(
                "artifact_id_mismatch", "UploadSession artifact_id does not match artifact.", component="upload_session"
            )
        )
    if upload_session.get("document_record_id") != str(artifact.document_record_id):
        blocking_issues.append(
            _issue(
                "document_record_id_mismatch",
                "UploadSession document_record_id does not match artifact.",
                component="upload_session",
            )
        )
    if upload_session.get("document_version_id") != str(artifact.document_version_id):
        blocking_issues.append(
            _issue(
                "document_version_id_mismatch",
                "UploadSession document_version_id does not match artifact.",
                component="upload_session",
            )
        )
    if not storage_operation_plan:
        blocking_issues.append(
            _issue(
                "storage_operation_plan_missing",
                "UploadSession is missing storage_operation_plan.",
                component="storage",
            )
        )
    if not runtime_trace:
        blocking_issues.append(
            _issue("runtime_trace_missing", "UploadSession is missing runtime_trace.", component="storage_runtime")
        )
    if not execution_flags:
        blocking_issues.append(
            _issue("execution_flags_missing", "UploadSession is missing execution_flags.", component="upload_session")
        )
    for key in UPLOAD_SESSION_FLAG_KEYS:
        if key not in execution_flags:
            warnings.append(
                _issue(
                    f"{key}_flag_missing",
                    f"UploadSession execution flag {key} is missing.",
                    component="upload_session",
                    severity="warning",
                )
            )
    if bool(execution_flags.get("file_uploaded")):
        warnings.append(
            _issue(
                "file_uploaded_unexpected",
                "Binary upload session reports file_uploaded=true before real upload exists.",
                component="upload_session",
                severity="warning",
            )
        )
    if bool(execution_flags.get("object_stored")):
        warnings.append(
            _issue(
                "object_stored_unexpected",
                "Binary upload session reports object_stored=true before storage execution exists.",
                component="storage",
                severity="warning",
            )
        )
    if bool(execution_flags.get("checksum_calculated")):
        warnings.append(
            _issue(
                "checksum_calculated_unexpected",
                "Binary upload session reports checksum_calculated=true before binary content exists.",
                component="checksum",
                severity="warning",
            )
        )
    if storage_operation_plan.get("operation_invoked"):
        warnings.append(
            _issue(
                "storage_operation_invoked_unexpected",
                "Storage operation should not be invoked in metadata-only upload session.",
                component="storage",
                severity="warning",
            )
        )
    if runtime_trace.get("operation_invoked"):
        warnings.append(
            _issue(
                "runtime_operation_invoked_unexpected",
                "Runtime operation should not be invoked in metadata-only upload session.",
                component="storage_runtime",
                severity="warning",
            )
        )
    if upload_artifact.get("artifact_type") != BINARY_UPLOAD_PLACEHOLDER_ARTIFACT_TYPE:
        blocking_issues.append(
            _issue("artifact_type_invalid", "Artifact is not a binary upload placeholder.", component="artifact")
        )
    return {
        "validation_status": "blocked" if blocking_issues else "valid",
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
        "validated_components": [
            "artifact",
            "document_record_id",
            "document_version_id",
            "storage_operation_plan",
            "runtime_trace",
            "execution_flags",
        ],
    }


def build_upload_session_control_capabilities(upload_session: dict[str, Any]) -> dict[str, Any]:
    runtime_state = upload_session.get("runtime_state")
    execution_flags = upload_session.get("execution_flags") or {}
    storage_operation_plan = upload_session.get("storage_operation_plan") or {}
    storage_configuration = upload_session.get("storage_configuration_readiness") or {}
    storage_configured = bool(storage_configuration.get("configured"))
    storage_execution_allowed = bool(storage_operation_plan.get("storage_execution_allowed"))
    no_real_binary = not execution_flags.get("file_uploaded") and not execution_flags.get("object_stored")
    return {
        "can_prepare_upload": {
            "available": False,
            "status": "blocked",
            "reason": "upload_control_action_endpoint_not_implemented",
            "future_action": "prepare_upload",
            "runtime_state": runtime_state,
        },
        "can_replace_placeholder": {
            "available": False,
            "status": "blocked",
            "reason": "placeholder_replacement_not_implemented",
            "future_action": "replace_placeholder",
        },
        "can_configure_storage": {
            "available": False,
            "status": "blocked",
            "reason": "storage_configuration_control_action_not_implemented"
            if not storage_configured
            else "storage_already_configured_or_ready_for_future_execution",
            "future_action": "configure_storage",
            "storage_provider_configured": storage_configured,
        },
        "can_execute_storage": {
            "available": False,
            "status": "blocked",
            "reason": "real_storage_execution_not_implemented"
            if storage_execution_allowed or storage_configured
            else "storage_provider_not_configured",
            "future_action": "execute_storage",
            "storage_execution_allowed": storage_execution_allowed,
            "runtime_state": runtime_state,
        },
        "can_start_ingestion": {
            "available": False,
            "status": "blocked",
            "reason": "binary_content_not_uploaded" if no_real_binary else "ingestion_control_action_not_implemented",
            "future_action": "start_ingestion",
        },
    }


def build_future_upload_session_actions(control_capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"action": "prepare_upload", **control_capabilities["can_prepare_upload"]},
        {"action": "replace_placeholder", **control_capabilities["can_replace_placeholder"]},
        {"action": "configure_storage", **control_capabilities["can_configure_storage"]},
        {"action": "execute_storage", **control_capabilities["can_execute_storage"]},
        {"action": "start_ingestion", **control_capabilities["can_start_ingestion"]},
    ]


def build_upload_session_status(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    artifact = _binary_upload_artifact_by_id(db, artifact_id=artifact_id)
    if artifact is None:
        return None

    upload_artifact = build_artifact_upload_session_data(artifact)
    placeholder = upload_artifact["artifact_placeholder_metadata"]
    upload_session = serialize_upload_session(build_upload_session_from_artifact_data(upload_artifact))
    session_validation = validate_upload_session(
        artifact=artifact,
        upload_artifact=upload_artifact,
        upload_session=upload_session,
    )
    control_capabilities = build_upload_session_control_capabilities(upload_session)
    upload_session = {
        **upload_session,
        "session_validation": session_validation,
        "control_capabilities": control_capabilities,
        "future_session_actions": build_future_upload_session_actions(control_capabilities),
    }
    processing_session = serialize_processing_session(build_processing_session(upload_session))
    storage_execution_prepare = build_prepared_storage_execution(upload_session)
    storage_execution_session = storage_execution_prepare["storage_execution_session"]
    execution_flags = upload_session["execution_flags"]
    return {
        "artifact_id": str(artifact.id),
        "upload_session_id": upload_session["upload_session_id"],
        "upload_session": upload_session,
        "storage_execution_session": storage_execution_session,
        "storage_execution_prepare": storage_execution_prepare,
        "storage_execution_prepare_available": True,
        "storage_execution_required_before_processing": True,
        "processing_blocked_reason": "storage_not_verified",
        "storage_execution_state": storage_execution_session["execution_state"],
        "storage_execution_plan": storage_execution_session["execution_plan"],
        "processing_session": processing_session,
        "processing_state": processing_session["processing_state"],
        "processing_plan": processing_session["processing_plan"],
        "processing_capabilities": processing_session["processing_capabilities"],
        "processing_pending_operations": processing_session["pending_operations"],
        "document_record_id": str(artifact.document_record_id),
        "document_version_id": str(artifact.document_version_id),
        "upload_status": placeholder["upload_status"],
        "storage_provider_name": placeholder["storage_provider_name"],
        "storage_provider_type": placeholder["storage_provider_type"],
        "storage_provider_configured": placeholder["storage_provider_configured"],
        "storage_provider_status": placeholder["storage_provider_status"],
        "storage_operation_plan": upload_session["storage_operation_plan"],
        "runtime_trace": upload_session["runtime_trace"],
        "runtime_state": upload_session["runtime_state"],
        "storage_operation_result": upload_session["storage_operation_result"],
        "provider_descriptor": upload_session["storage_provider_descriptor"],
        "capabilities": (upload_session["storage_provider_descriptor"] or {}).get("capabilities") or [],
        "storage_configuration_readiness": upload_session["storage_configuration_readiness"],
        "missing_configuration_reason": (upload_session["storage_operation_plan"] or {}).get(
            "missing_configuration_reason"
        ),
        "required_next_step": (upload_session["storage_operation_plan"] or {}).get("required_next_step"),
        "flags": {key: execution_flags[key] for key in UPLOAD_SESSION_FLAG_KEYS},
        "session_validation": session_validation,
        "control_capabilities": control_capabilities,
        "future_session_actions": upload_session["future_session_actions"],
        "blocking_issues": session_validation["blocking_issues"],
        "warnings": session_validation["warnings"],
        "next_available_actions": upload_session["next_available_actions"],
    }
