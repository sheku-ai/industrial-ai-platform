"""Processing handoff foundation from verified storage execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.document_processing_session import build_processing_session, serialize_processing_session

PROCESSING_HANDOFF_SESSION_SCHEMA_VERSION = "1"
PROCESSING_HANDOFF_STATUS_BLOCKED = "blocked"
PROCESSING_HANDOFF_STATUS_READY = "ready"


@dataclass(frozen=True)
class ProcessingHandoffSession:
    handoff_session_id: str | None
    artifact_id: str | None
    upload_session_id: str | None
    execution_session_id: str | None
    storage_verified: bool
    processing_handoff_prerequisite_met: bool
    processing_handoff_allowed: bool
    handoff_status: str
    handoff_blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    handoff_warnings: list[dict[str, Any]] = field(default_factory=list)
    source_storage_summary: dict[str, Any] = field(default_factory=dict)
    processing_session: dict[str, Any] = field(default_factory=dict)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


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


def _handoff_session_id(*, artifact_id: str | None) -> str | None:
    if not artifact_id:
        return None
    return f"processing-handoff-session:{artifact_id}"


def _source_value(storage_execution_status: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in storage_execution_status:
        return storage_execution_status.get(key)
    execution_request = storage_execution_status.get("execution_request")
    if isinstance(execution_request, dict) and key in execution_request:
        return execution_request.get(key)
    return default


def _source_provider_descriptor(storage_execution_status: dict[str, Any]) -> dict[str, Any]:
    provider_descriptor = storage_execution_status.get("provider_descriptor")
    if isinstance(provider_descriptor, dict):
        return provider_descriptor
    execution_request = storage_execution_status.get("execution_request")
    if isinstance(execution_request, dict) and isinstance(execution_request.get("provider_descriptor"), dict):
        return execution_request["provider_descriptor"]
    prepared_execution = storage_execution_status.get("prepared_execution")
    if isinstance(prepared_execution, dict) and isinstance(prepared_execution.get("provider_descriptor"), dict):
        return prepared_execution["provider_descriptor"]
    return {}


def build_source_storage_summary(storage_execution_status: dict[str, Any]) -> dict[str, Any]:
    execution_request = storage_execution_status.get("execution_request")
    storage_execution_session = storage_execution_status.get("storage_execution_session")
    provider_descriptor = _source_provider_descriptor(storage_execution_status)
    if not isinstance(storage_execution_session, dict) and isinstance(execution_request, dict):
        storage_execution_session = execution_request.get("storage_execution_session")
    if not isinstance(storage_execution_session, dict):
        storage_execution_session = {}
    return {
        "artifact_id": _source_value(storage_execution_status, "artifact_id"),
        "document_record_id": _source_value(storage_execution_status, "document_record_id"),
        "document_version_id": _source_value(storage_execution_status, "document_version_id"),
        "upload_session_id": _source_value(storage_execution_status, "upload_session_id"),
        "execution_session_id": _source_value(storage_execution_status, "execution_session_id")
        or storage_execution_session.get("execution_session_id"),
        "storage_verified": bool(_source_value(storage_execution_status, "storage_verified")),
        "processing_handoff_prerequisite_met": bool(
            _source_value(storage_execution_status, "processing_handoff_prerequisite_met")
        ),
        "processing_handoff_allowed": bool(_source_value(storage_execution_status, "processing_handoff_allowed")),
        "object_handle": _source_value(storage_execution_status, "object_handle"),
        "object_exists": bool(_source_value(storage_execution_status, "object_exists")),
        "object_stored": bool(_source_value(storage_execution_status, "object_stored")),
        "file_uploaded": bool(_source_value(storage_execution_status, "file_uploaded")),
        "checksum_calculated": bool(_source_value(storage_execution_status, "checksum_calculated")),
        "checksum": _source_value(storage_execution_status, "checksum"),
        "content_length": _source_value(storage_execution_status, "content_length"),
        "content_type": _source_value(storage_execution_status, "content_type"),
        "storage_verification_status": _source_value(
            storage_execution_status, "storage_verification_status", "not_verified"
        ),
        "storage_verification_available": bool(
            _source_value(storage_execution_status, "storage_verification_available")
        ),
        "storage_provider_name": _source_value(storage_execution_status, "storage_provider_name")
        or provider_descriptor.get("provider_name"),
        "storage_provider_type": _source_value(storage_execution_status, "storage_provider_type")
        or provider_descriptor.get("provider_type"),
        "deleted": bool(_source_value(storage_execution_status, "deleted")),
    }


def _upload_session_for_processing(
    storage_execution_status: dict[str, Any], source_summary: dict[str, Any]
) -> dict[str, Any]:
    upload_session = storage_execution_status.get("upload_session")
    if not isinstance(upload_session, dict):
        execution_request = storage_execution_status.get("execution_request")
        upload_session = (
            execution_request.get("storage_execution_session") if isinstance(execution_request, dict) else {}
        )
    upload_session = dict(upload_session or {})
    flags = dict(upload_session.get("execution_flags") or {})
    flags.update(
        {
            "file_uploaded": bool(source_summary.get("file_uploaded")),
            "object_stored": bool(source_summary.get("object_stored")),
            "checksum_calculated": bool(source_summary.get("checksum_calculated")),
            "ingestion_executed": False,
            "chunks_created": False,
            "embeddings_created": False,
            "ai_required": False,
            "vector_store_required": False,
        }
    )
    upload_session.update(
        {
            "artifact_id": upload_session.get("artifact_id") or source_summary.get("artifact_id"),
            "document_record_id": upload_session.get("document_record_id") or source_summary.get("document_record_id"),
            "document_version_id": upload_session.get("document_version_id")
            or source_summary.get("document_version_id"),
            "upload_session_id": upload_session.get("upload_session_id") or source_summary.get("upload_session_id"),
            "execution_flags": flags,
        }
    )
    return upload_session


def _validate_handoff(
    *,
    artifact_id: str | None,
    source_summary: dict[str, Any],
    upload_session: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not artifact_id:
        blocking_issues.append(
            _issue("artifact_id_missing", "Processing handoff requires an artifact_id.", component="processing_handoff")
        )
    if not upload_session.get("upload_session_id"):
        blocking_issues.append(
            _issue(
                "upload_session_missing",
                "Processing handoff requires an upload_session_id.",
                component="upload_session",
            )
        )
    if not source_summary.get("execution_session_id"):
        blocking_issues.append(
            _issue(
                "storage_execution_session_missing",
                "Processing handoff requires a storage execution session.",
                component="storage_execution",
            )
        )
    required_true_fields = {
        "storage_verified": "Storage must be verified before processing handoff can be prepared.",
        "processing_handoff_prerequisite_met": "Storage handoff prerequisite must be met before processing handoff.",
        "object_exists": "Stored object must exist before processing handoff.",
        "object_stored": "Stored object must be marked stored before processing handoff.",
        "file_uploaded": "Binary file must be uploaded before processing handoff.",
        "checksum_calculated": "Checksum must be calculated before processing handoff.",
    }
    for field_name, message in required_true_fields.items():
        if not bool(source_summary.get(field_name)):
            blocking_issues.append(_issue(f"{field_name}_required", message, component="processing_handoff"))
    if not source_summary.get("object_handle"):
        blocking_issues.append(
            _issue(
                "object_handle_required",
                "Processing handoff requires a storage object_handle.",
                component="processing_handoff",
            )
        )
    if source_summary.get("deleted"):
        blocking_issues.append(
            _issue(
                "object_deleted",
                "Deleted storage objects cannot be handed off to processing.",
                component="processing_handoff",
            )
        )
    if source_summary.get("processing_handoff_allowed"):
        warnings.append(
            _issue(
                "storage_processing_handoff_allowed_unexpected",
                "Storage execution must not be the authority for enabling processing runtime execution.",
                component="processing_handoff",
                severity="warning",
            )
        )
    return _sort_issues(blocking_issues), _sort_issues(warnings)


def _next_processing_actions(handoff_status: str) -> list[dict[str, Any]]:
    ready = handoff_status == PROCESSING_HANDOFF_STATUS_READY
    return [
        {
            "action": "prepare_processing_session",
            "available": ready,
            "status": "ready" if ready else "blocked",
            "processing_started": False,
            "processing_completed": False,
            "ingestion_job_created": False,
        },
        {
            "action": "start_processing",
            "available": ready,
            "status": "ready" if ready else "blocked",
            "reason": None if ready else "processing_handoff_not_ready",
            "processing_started": False,
            "processing_completed": False,
            "ingestion_job_created": False,
        },
    ]


def serialize_processing_handoff_session(session: ProcessingHandoffSession) -> dict[str, Any]:
    return {
        "processing_handoff_session_schema_version": PROCESSING_HANDOFF_SESSION_SCHEMA_VERSION,
        "handoff_session_id": session.handoff_session_id,
        "artifact_id": session.artifact_id,
        "upload_session_id": session.upload_session_id,
        "execution_session_id": session.execution_session_id,
        "storage_verified": session.storage_verified,
        "processing_handoff_prerequisite_met": session.processing_handoff_prerequisite_met,
        "processing_handoff_allowed": session.processing_handoff_allowed,
        "processing_handoff_ready": session.handoff_status == PROCESSING_HANDOFF_STATUS_READY,
        "handoff_status": session.handoff_status,
        "handoff_blocking_issues": list(session.handoff_blocking_issues),
        "handoff_warnings": list(session.handoff_warnings),
        "source_storage_summary": dict(session.source_storage_summary),
        "processing_session": dict(session.processing_session),
        "next_available_actions": list(session.next_available_actions),
        "processing_started": False,
        "processing_completed": False,
        "ingestion_job_created": False,
        "chunks_created": False,
        "embeddings_created": False,
        "ai_required": False,
    }


def build_document_processing_handoff(
    *,
    artifact_id: str | None,
    storage_execution_status: dict[str, Any],
) -> dict[str, Any]:
    source_summary = build_source_storage_summary(storage_execution_status)
    resolved_artifact_id = str(artifact_id) if artifact_id else source_summary.get("artifact_id")
    upload_session = _upload_session_for_processing(storage_execution_status, source_summary)
    blocking_issues, warnings = _validate_handoff(
        artifact_id=resolved_artifact_id,
        source_summary=source_summary,
        upload_session=upload_session,
    )
    processing_session = serialize_processing_session(build_processing_session(upload_session))
    handoff_status = PROCESSING_HANDOFF_STATUS_BLOCKED if blocking_issues else PROCESSING_HANDOFF_STATUS_READY
    next_available_actions = _next_processing_actions(handoff_status)
    processing_allowed = handoff_status == PROCESSING_HANDOFF_STATUS_READY
    session = ProcessingHandoffSession(
        handoff_session_id=_handoff_session_id(artifact_id=resolved_artifact_id),
        artifact_id=resolved_artifact_id,
        upload_session_id=upload_session.get("upload_session_id"),
        execution_session_id=source_summary.get("execution_session_id"),
        storage_verified=bool(source_summary.get("storage_verified")),
        processing_handoff_prerequisite_met=bool(source_summary.get("processing_handoff_prerequisite_met")),
        processing_handoff_allowed=processing_allowed,
        handoff_status=handoff_status,
        handoff_blocking_issues=blocking_issues,
        handoff_warnings=warnings,
        source_storage_summary=source_summary,
        processing_session=processing_session,
        next_available_actions=next_available_actions,
    )
    serialized = serialize_processing_handoff_session(session)
    return {
        **serialized,
        "handoff_session": serialized,
        "next_processing_actions": next_available_actions,
    }
