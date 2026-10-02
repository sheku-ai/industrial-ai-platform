"""Upload Session domain for metadata-only binary upload attempts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

UPLOAD_SESSION_SCHEMA_VERSION = "1"
UPLOAD_SESSION_EXECUTION_MODE_PREPARED = "prepared_only"

UPLOAD_SESSION_FLAG_KEYS = (
    "file_uploaded",
    "object_stored",
    "checksum_calculated",
    "ingestion_executed",
    "chunks_created",
    "embeddings_created",
    "ai_required",
    "vector_store_required",
)

UPLOAD_SESSION_FALSE_FLAGS = {
    "file_uploaded": False,
    "object_stored": False,
    "checksum_calculated": False,
    "storage_verified": False,
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


@dataclass(frozen=True)
class UploadSession:
    upload_session_id: str | None
    artifact_id: str | None
    document_record_id: str | None
    document_version_id: str | None
    requested_operation: str
    execution_mode: str
    runtime_state: str | None
    storage_provider_descriptor: dict[str, Any] = field(default_factory=dict)
    storage_operation_plan: dict[str, Any] = field(default_factory=dict)
    runtime_trace: dict[str, Any] = field(default_factory=dict)
    storage_operation_result: dict[str, Any] = field(default_factory=dict)
    execution_flags: dict[str, Any] = field(default_factory=dict)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)
    future_capabilities: dict[str, Any] = field(default_factory=dict)
    storage_configuration_readiness: dict[str, Any] = field(default_factory=dict)


def _session_id(*, artifact_id: str | None, document_version_id: str | None) -> str | None:
    if artifact_id:
        return f"upload-session:{artifact_id}"
    if document_version_id:
        return f"upload-session:pending:{document_version_id}"
    return None


def _execution_flags(source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    flags = dict(UPLOAD_SESSION_FALSE_FLAGS)
    for key in (*UPLOAD_SESSION_FLAG_KEYS, "storage_verified", "workflow_executed", "ai_vector_not_required"):
        if key in source:
            flags[key] = bool(source.get(key))
    flags["object_handle"] = source.get("object_handle")
    flags["checksum"] = source.get("checksum")
    flags["content_length"] = source.get("content_length")
    flags["content_type"] = source.get("content_type")
    flags["storage_provider_name"] = source.get("storage_provider_name") or "null"
    flags["storage_provider_type"] = source.get("storage_provider_type") or "null"
    flags["storage_provider_configured"] = bool(source.get("storage_provider_configured"))
    flags["storage_provider_status"] = source.get("storage_provider_status") or "storage_not_configured"
    flags["storage_operation"] = source.get("storage_operation") or "none"
    flags["upload_record_created"] = bool(source.get("upload_record_created"))
    return flags


def _next_available_actions(*, placeholder_available: bool, runtime_state: str | None) -> list[dict[str, Any]]:
    return [
        {
            "action": "attach_binary_content",
            "available": bool(placeholder_available),
            "executed": False,
            "status": "ready" if placeholder_available else "not_available",
            "reason": "storage_provider_execution_is_future_capability",
            "runtime_state": runtime_state,
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


def _future_capabilities() -> dict[str, Any]:
    return {
        "real_upload": {"prepared": True, "implemented": False, "executed": False},
        "multipart_upload": {"prepared": True, "implemented": False, "executed": False},
        "resumable_upload": {"prepared": True, "implemented": False, "executed": False},
        "retries": {"prepared": True, "implemented": False, "executed": False},
        "checksum": {"prepared": True, "implemented": False, "executed": False},
        "object_versioning": {"prepared": True, "implemented": False, "executed": False},
    }


def build_upload_session(
    *,
    artifact_id: str | None,
    document_record_id: str | None,
    document_version_id: str | None,
    storage_operation_plan: dict[str, Any] | None = None,
    runtime_trace: dict[str, Any] | None = None,
    provider_descriptor: dict[str, Any] | None = None,
    execution_flags: dict[str, Any] | None = None,
    storage_configuration_readiness: dict[str, Any] | None = None,
    placeholder_available: bool,
) -> UploadSession:
    storage_operation_plan = dict(storage_operation_plan or {})
    runtime_trace = dict(runtime_trace or storage_operation_plan.get("runtime_trace") or {})
    provider_descriptor = dict(
        provider_descriptor
        or storage_operation_plan.get("provider_descriptor")
        or runtime_trace.get("provider_descriptor")
        or {}
    )
    flag_source = {
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_configured": provider_descriptor.get("configured"),
        "storage_provider_status": provider_descriptor.get("status"),
        "storage_operation": storage_operation_plan.get("storage_operation"),
        **dict(execution_flags or {}),
    }
    operation_result = dict(
        storage_operation_plan.get("operation_result") or runtime_trace.get("operation_result") or {}
    )
    requested_operation = (
        runtime_trace.get("requested_operation")
        or storage_operation_plan.get("planned_operation")
        or operation_result.get("operation")
        or "generate_upload"
    )
    runtime_state = runtime_trace.get("runtime_state") or storage_operation_plan.get("runtime_state")
    return UploadSession(
        upload_session_id=_session_id(artifact_id=artifact_id, document_version_id=document_version_id),
        artifact_id=artifact_id,
        document_record_id=document_record_id,
        document_version_id=document_version_id,
        requested_operation=str(requested_operation),
        execution_mode=UPLOAD_SESSION_EXECUTION_MODE_PREPARED,
        runtime_state=str(runtime_state) if runtime_state is not None else None,
        storage_provider_descriptor=provider_descriptor,
        storage_operation_plan=storage_operation_plan,
        runtime_trace=runtime_trace,
        storage_operation_result=operation_result,
        execution_flags=_execution_flags(flag_source),
        next_available_actions=_next_available_actions(
            placeholder_available=placeholder_available,
            runtime_state=str(runtime_state) if runtime_state is not None else None,
        ),
        future_capabilities=_future_capabilities(),
        storage_configuration_readiness=dict(storage_configuration_readiness or {}),
    )


def build_upload_session_from_artifact_data(
    artifact_data: dict[str, Any],
    *,
    upload_record_created: bool = False,
) -> UploadSession:
    placeholder = artifact_data.get("artifact_placeholder_metadata") or {}
    execution_flags = {
        **artifact_data,
        "upload_record_created": upload_record_created,
    }
    return build_upload_session(
        artifact_id=artifact_data.get("id"),
        document_record_id=artifact_data.get("document_record_id"),
        document_version_id=artifact_data.get("document_version_id"),
        storage_operation_plan=artifact_data.get("storage_operation_plan"),
        runtime_trace=artifact_data.get("runtime_trace"),
        provider_descriptor=artifact_data.get("provider_descriptor"),
        execution_flags=execution_flags,
        storage_configuration_readiness=artifact_data.get("storage_configuration_readiness")
        or placeholder.get("storage_configuration_readiness"),
        placeholder_available=True,
    )


def build_upload_session_from_execution_context(
    *,
    artifact_id: str | None,
    document_record_id: str | None,
    document_version_id: str | None,
    storage_operation_plan: dict[str, Any] | None,
    runtime_trace: dict[str, Any] | None,
    provider_descriptor: dict[str, Any] | None,
    execution_flags: dict[str, Any] | None,
    storage_configuration_readiness: dict[str, Any] | None,
    placeholder_available: bool,
) -> UploadSession:
    return build_upload_session(
        artifact_id=artifact_id,
        document_record_id=document_record_id,
        document_version_id=document_version_id,
        storage_operation_plan=storage_operation_plan,
        runtime_trace=runtime_trace,
        provider_descriptor=provider_descriptor,
        execution_flags=execution_flags,
        storage_configuration_readiness=storage_configuration_readiness,
        placeholder_available=placeholder_available,
    )


def serialize_upload_session(upload_session: UploadSession) -> dict[str, Any]:
    return {
        "upload_session_schema_version": UPLOAD_SESSION_SCHEMA_VERSION,
        "upload_session_id": upload_session.upload_session_id,
        "artifact_id": upload_session.artifact_id,
        "document_record_id": upload_session.document_record_id,
        "document_version_id": upload_session.document_version_id,
        "requested_operation": upload_session.requested_operation,
        "execution_mode": upload_session.execution_mode,
        "runtime_state": upload_session.runtime_state,
        "storage_provider_descriptor": upload_session.storage_provider_descriptor,
        "storage_operation_plan": upload_session.storage_operation_plan,
        "runtime_trace": upload_session.runtime_trace,
        "storage_operation_result": upload_session.storage_operation_result,
        "execution_flags": upload_session.execution_flags,
        "storage_configuration_readiness": upload_session.storage_configuration_readiness,
        "future_capabilities": upload_session.future_capabilities,
        "multipart_upload": upload_session.future_capabilities["multipart_upload"],
        "resumable_upload": upload_session.future_capabilities["resumable_upload"],
        "retries": upload_session.future_capabilities["retries"],
        "checksum": upload_session.future_capabilities["checksum"],
        "object_versioning": upload_session.future_capabilities["object_versioning"],
        "next_available_actions": upload_session.next_available_actions,
    }
