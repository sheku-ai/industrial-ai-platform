"""Read-only control plane for storage execution sessions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.document_binary_upload_control_plane import build_upload_session_status
from app.services.runtime_persistence_runtime import persist_runtime_outputs
from app.services.storage_execution_gateway import (
    build_prepared_storage_execution,
    build_storage_execution_memory_state,
    build_storage_execution_request,
)


def build_storage_execution_status(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None

    upload_session = upload_status["upload_session"]
    prepared_execution = upload_status.get("storage_execution_prepare") or build_prepared_storage_execution(
        upload_session
    )
    memory_state = build_storage_execution_memory_state(upload_session)
    storage_execution_session = prepared_execution["storage_execution_session"]
    validation = storage_execution_session["validation_result"]
    flags = upload_session.get("execution_flags") if isinstance(upload_session.get("execution_flags"), dict) else {}
    persisted_storage_verified = bool(flags.get("storage_verified"))
    storage_verified = persisted_storage_verified or bool(memory_state.get("storage_verified"))
    object_exists = bool(memory_state.get("object_exists") or flags.get("object_stored") or flags.get("file_uploaded"))
    object_stored = bool(memory_state.get("object_stored") or flags.get("object_stored"))
    file_uploaded = bool(memory_state.get("file_uploaded") or flags.get("file_uploaded"))
    checksum_calculated = bool(memory_state.get("checksum_calculated") or flags.get("checksum_calculated"))
    object_handle = memory_state.get("object_handle") or flags.get("object_handle")
    checksum = memory_state.get("checksum") or flags.get("checksum")
    content_length = memory_state.get("content_length") or flags.get("content_length")
    content_type = memory_state.get("content_type") or flags.get("content_type")
    return {
        "artifact_id": str(artifact_id),
        "upload_session_id": upload_session.get("upload_session_id"),
        "execution_session_id": storage_execution_session["execution_session_id"],
        "execution_state": storage_execution_session["execution_state"],
        "storage_execution_session": storage_execution_session,
        "execution_plan": storage_execution_session["execution_plan"],
        "validation": validation,
        "validation_summary": prepared_execution["validation_summary"],
        "prepare_available": prepared_execution["prepare_available"],
        "executable": False,
        "verification_required": True,
        "processing_handoff_allowed": False,
        "processing_handoff_prerequisite_met": storage_verified,
        "processing_handoff_prepare_available": True,
        "processing_handoff_endpoint": f"/api/documents/processing/{artifact_id}/handoff/prepare",
        "processing_blocked_reason": prepared_execution["processing_blocked_reason"],
        "request_supported": True,
        "execution_request_required_before_execution": True,
        "latest_execution_request": None,
        "request_persistence_supported": False,
        "request_persistence_required_before_execution": True,
        "latest_execution_request_descriptor": None,
        "storage_verification_supported": True,
        "storage_verification_required_before_processing": True,
        "latest_storage_verification": None,
        "latest_storage_verification_descriptor": None,
        "storage_verification_status": "storage_verified" if storage_verified else "not_verified",
        "storage_verification_available": storage_verified,
        "storage_provider_type": memory_state.get("storage_provider_type")
        or (storage_execution_session["provider_descriptor"] or {}).get("provider_type"),
        "storage_verified": storage_verified,
        "object_exists": object_exists,
        "object_handle": object_handle,
        "object_stored": object_stored,
        "file_uploaded": file_uploaded,
        "checksum_calculated": checksum_calculated,
        "checksum": checksum,
        "content_length": content_length,
        "content_type": content_type,
        "deleted": bool(memory_state.get("deleted")),
        "storage_execution_result_supported": True,
        "storage_execution_result_required_before_verification": True,
        "latest_storage_execution_result": None,
        "latest_storage_execution_result_descriptor": None,
        "storage_execution_result_status": "not_executed",
        "action_model": prepared_execution["action_model"],
        "provider_descriptor": storage_execution_session["provider_descriptor"],
        "runtime_trace": storage_execution_session["runtime_trace"],
        "next_available_actions": storage_execution_session["next_available_actions"],
        "blocking_issues": validation["blocking_issues"],
        "warnings": validation["warnings"],
        "upload_session": upload_session,
        "upload_session_validation": upload_status.get("session_validation"),
    }


def build_storage_execution_prepare(
    db: Session,
    *,
    artifact_id: uuid.UUID,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None

    upload_session = upload_status["upload_session"]
    prepared_execution = upload_status.get("storage_execution_prepare") or build_prepared_storage_execution(
        upload_session
    )
    memory_state = build_storage_execution_memory_state(upload_session)
    flags = upload_session.get("execution_flags") if isinstance(upload_session.get("execution_flags"), dict) else {}
    persisted_storage_verified = bool(flags.get("storage_verified"))
    storage_verified = persisted_storage_verified or bool(memory_state.get("storage_verified"))
    object_exists = bool(memory_state.get("object_exists") or flags.get("object_stored") or flags.get("file_uploaded"))
    object_stored = bool(memory_state.get("object_stored") or flags.get("object_stored"))
    file_uploaded = bool(memory_state.get("file_uploaded") or flags.get("file_uploaded"))
    checksum_calculated = bool(memory_state.get("checksum_calculated") or flags.get("checksum_calculated"))
    object_handle = memory_state.get("object_handle") or flags.get("object_handle")
    checksum = memory_state.get("checksum") or flags.get("checksum")
    content_length = memory_state.get("content_length") or flags.get("content_length")
    content_type = memory_state.get("content_type") or flags.get("content_type")
    return {
        "artifact_id": str(artifact_id),
        "upload_session_id": upload_session.get("upload_session_id"),
        "prepared_execution": prepared_execution["prepared_execution"],
        "storage_execution_session": prepared_execution["storage_execution_session"],
        "execution_plan": prepared_execution["execution_plan"],
        "validation": prepared_execution["validation"],
        "validation_summary": prepared_execution["validation_summary"],
        "action_model": prepared_execution["action_model"],
        "provider_descriptor": prepared_execution["provider_descriptor"],
        "runtime_trace": prepared_execution["runtime_trace"],
        "next_available_actions": prepared_execution["next_available_actions"],
        "prepared": True,
        "prepare_available": True,
        "executable": False,
        "verification_required": True,
        "processing_handoff_allowed": False,
        "processing_handoff_prerequisite_met": storage_verified,
        "processing_blocked_reason": "storage_not_verified",
        "storage_verification_supported": True,
        "storage_verification_required_before_processing": True,
        "latest_storage_verification": None,
        "latest_storage_verification_descriptor": None,
        "storage_verification_status": "storage_verified" if storage_verified else "not_verified",
        "storage_verification_available": storage_verified,
        "storage_provider_type": memory_state.get("storage_provider_type")
        or (prepared_execution["provider_descriptor"] or {}).get("provider_type"),
        "storage_verified": storage_verified,
        "object_exists": object_exists,
        "object_handle": object_handle,
        "object_stored": object_stored,
        "file_uploaded": file_uploaded,
        "checksum_calculated": checksum_calculated,
        "checksum": checksum,
        "content_length": content_length,
        "content_type": content_type,
        "deleted": bool(memory_state.get("deleted")),
        "storage_execution_result_supported": True,
        "storage_execution_result_required_before_verification": True,
        "latest_storage_execution_result": None,
        "latest_storage_execution_result_descriptor": None,
        "storage_execution_result_status": "not_executed",
        "blocking_issues": prepared_execution["validation"]["blocking_issues"],
        "warnings": prepared_execution["validation"]["warnings"],
        "upload_session": upload_session,
        "upload_session_validation": upload_status.get("session_validation"),
    }


def build_storage_execution_request_status(
    db: Session,
    *,
    artifact_id: uuid.UUID,
    requested_operation: str,
    requested_by: str | None = None,
    request_metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any] | None:
    upload_status = build_upload_session_status(db, artifact_id=artifact_id)
    if upload_status is None:
        return None

    upload_session = upload_status["upload_session"]
    request_result = build_storage_execution_request(
        upload_session,
        requested_operation=requested_operation,
        requested_by=requested_by,
        request_metadata=request_metadata,
        idempotency_key=idempotency_key,
    )
    execution_request = request_result["execution_request"]
    object_exists = bool(request_result.get("object_exists"))
    result_descriptor = request_result["result_descriptor"]
    verification_descriptor = request_result["verification_descriptor"]
    storage_verified = bool(request_result.get("storage_verified"))
    storage_verification_status = (
        request_result.get("storage_verification_status")
        or verification_descriptor.get("verification_status")
        or "not_verified"
    )
    response = {
        "artifact_id": str(artifact_id),
        "upload_session_id": upload_session.get("upload_session_id"),
        "execution_session_id": execution_request["execution_session_id"],
        "execution_request": execution_request,
        "request_descriptor": request_result["request_descriptor"],
        "descriptor_validation": request_result["descriptor_validation"],
        "future_persistence_descriptor": request_result["future_persistence_descriptor"],
        "verification_descriptor": request_result["verification_descriptor"],
        "verification_validation": request_result["verification_validation"],
        "result_descriptor": request_result["result_descriptor"],
        "result_validation": request_result["result_validation"],
        "prepared_execution": request_result["prepared_execution"],
        "validation": request_result["validation"],
        "blocking_issues": request_result["blocking_issues"],
        "warnings": request_result["warnings"],
        "next_available_actions": request_result["next_available_actions"],
        "request_supported": True,
        "execution_request_required_before_execution": True,
        "latest_execution_request": None,
        "request_persistence_supported": False,
        "request_persistence_required_before_execution": True,
        "latest_execution_request_descriptor": None,
        "request_persisted": False,
        "persistence_required": False,
        "persistence_available": False,
        "persistence_status": "not_persisted",
        "verification_required": True,
        "verification_available": bool(request_result.get("verification_available")),
        "storage_verification_supported": True,
        "storage_verification_required_before_processing": True,
        "latest_storage_verification": execution_request.get("storage_verification_result"),
        "latest_storage_verification_descriptor": verification_descriptor,
        "storage_verification_status": storage_verification_status,
        "storage_verification_available": bool(request_result.get("storage_verification_available"))
        or bool(request_result.get("verification_available")),
        "storage_verified": storage_verified,
        "processing_handoff_allowed": False,
        "processing_handoff_prerequisite_met": storage_verified,
        "object_exists": object_exists,
        "object_handle": execution_request.get("object_handle"),
        "checksum": result_descriptor.get("checksum"),
        "content_length": result_descriptor.get("content_length"),
        "content_type": result_descriptor.get("content_type"),
        "content_available": bool(execution_request.get("content_available")),
        "content_returned": bool(execution_request.get("content_returned")),
        "deleted": bool(execution_request.get("deleted")),
        "object_verification_status": storage_verification_status,
        "verification_persistence_status": "not_persisted",
        "result_required": True,
        "result_available": bool(request_result.get("result_available")),
        "storage_execution_result_supported": True,
        "storage_execution_result_required_before_verification": True,
        "latest_storage_execution_result": None,
        "latest_storage_execution_result_descriptor": None,
        "storage_execution_result_status": result_descriptor.get("result_status") or "not_executed",
        "result_persistence_status": "not_persisted",
        "execution_allowed": bool(execution_request.get("execution_allowed")),
        "operation_invoked": bool(execution_request.get("operation_invoked")),
        "real_storage_operations_enabled": bool(execution_request.get("real_storage_operations_enabled")),
        "object_stored": bool(result_descriptor.get("object_stored")),
        "file_uploaded": bool(result_descriptor.get("file_uploaded")),
        "checksum_calculated": bool(result_descriptor.get("checksum_calculated")),
        "provider_descriptor": execution_request["provider_descriptor"],
        "upload_session": upload_session,
        "upload_session_validation": upload_status.get("session_validation"),
    }
    response["runtime_persistence"] = persist_runtime_outputs(
        db,
        execution_id=str(response.get("execution_session_id") or f"storage-runtime:{artifact_id}"),
        artifact_id=str(artifact_id),
        runtime_outputs={"storage": response},
    )
    return response
