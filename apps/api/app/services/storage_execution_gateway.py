"""Storage execution gateway foundation.

This module is the only internal entry point for future storage execution flows.
It prepares execution sessions from UploadSession state without invoking any
provider operation or writing binary content.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.services.storage_provider_registry import get_storage_provider_registry
from app.services.storage_provider_runtime import (
    STORAGE_OPERATION_STATE_BLOCKED,
    STORAGE_OPERATION_STATE_FUTURE_READY,
    STORAGE_OPERATION_STATE_NOT_CONFIGURED,
    get_storage_provider_runtime_adapter,
)

STORAGE_EXECUTION_SESSION_SCHEMA_VERSION = "1"
STORAGE_EXECUTION_STATE_BLOCKED = "blocked"
STORAGE_EXECUTION_STATE_PLANNED = "planned"
STORAGE_EXECUTION_MODE_READINESS_ONLY = "readiness_only"

STORAGE_EXECUTION_OPERATIONS = (
    "create_object",
    "upload_object",
    "head_object",
    "get_object",
    "verify_object",
    "replace_object",
    "delete_object",
    "download_object",
)

STORAGE_EXECUTION_ACTIONS = (
    "prepare_create",
    "prepare_upload",
    "prepare_head",
    "prepare_get",
    "prepare_replace",
    "prepare_delete",
    "prepare_download",
    "verify_object",
    "mark_storage_verified",
    "handoff_to_processing",
)

STORAGE_EXECUTION_OPERATION_MAP = {
    "create_object": "create",
    "upload_object": "upload",
    "head_object": "head",
    "get_object": "get",
    "verify_object": "head",
    "replace_object": "upload",
    "delete_object": "delete",
    "download_object": "download",
}

STORAGE_EXECUTION_ACTION_OPERATION_MAP = {
    "prepare_create": "create_object",
    "prepare_upload": "upload_object",
    "prepare_head": "head_object",
    "prepare_get": "get_object",
    "prepare_replace": "replace_object",
    "prepare_delete": "delete_object",
    "prepare_download": "download_object",
    "verify_object": "verify_object",
    "mark_storage_verified": "download_object",
    "handoff_to_processing": "download_object",
}

STORAGE_EXECUTION_REQUEST_STATUS_BLOCKED = "blocked"
STORAGE_EXECUTION_REQUEST_STATUS_REQUESTED = "execution_requested"


@dataclass(frozen=True)
class StorageExecutionSession:
    execution_session_id: str | None
    upload_session_id: str | None
    artifact_id: str | None
    provider_descriptor: dict[str, Any]
    operation: str
    execution_state: str
    execution_plan: dict[str, Any] = field(default_factory=dict)
    validation_result: dict[str, Any] = field(default_factory=dict)
    runtime_trace: dict[str, Any] = field(default_factory=dict)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class StorageExecutionRequestDescriptor:
    request_id: str | None
    artifact_id: str | None
    upload_session_id: str | None
    execution_session_id: str | None
    requested_operation: str | None
    requested_by: str | None
    request_metadata: dict[str, Any]
    request_status: str | None
    idempotency_key: str | None
    provider_name: str | None
    provider_type: str | None
    provider_configured: bool
    execution_allowed: bool
    operation_invoked: bool
    object_stored: bool
    file_uploaded: bool
    checksum_calculated: bool
    validation_status: str | None
    blocking_issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    created_from: str
    persistence_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "storage_execution_request_descriptor_schema_version": "1",
            "request_id": self.request_id,
            "artifact_id": self.artifact_id,
            "upload_session_id": self.upload_session_id,
            "execution_session_id": self.execution_session_id,
            "requested_operation": self.requested_operation,
            "requested_by": self.requested_by,
            "request_metadata": dict(self.request_metadata),
            "request_status": self.request_status,
            "idempotency_key": self.idempotency_key,
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "storage_provider_name": self.provider_name,
            "storage_provider_type": self.provider_type,
            "provider_configured": self.provider_configured,
            "execution_allowed": self.execution_allowed,
            "operation_invoked": self.operation_invoked,
            "object_stored": self.object_stored,
            "file_uploaded": self.file_uploaded,
            "checksum_calculated": self.checksum_calculated,
            "validation_status": self.validation_status,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "created_from": self.created_from,
            "persistence_status": self.persistence_status,
        }


@dataclass(frozen=True)
class StorageExecutionVerificationDescriptor:
    verification_id: str | None
    request_id: str | None
    artifact_id: str | None
    upload_session_id: str | None
    execution_session_id: str | None
    requested_operation: str | None
    verification_status: str
    verification_required: bool
    verification_available: bool
    storage_verified: bool
    object_exists: bool
    object_stored: bool
    file_uploaded: bool
    checksum_calculated: bool
    provider_name: str | None
    provider_type: str | None
    provider_configured: bool
    object_handle: dict[str, Any] | None
    checksum: str | None
    content_length: int | None
    content_type: str | None
    metadata: dict[str, Any]
    blocking_issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    persistence_status: str

    def as_dict(self) -> dict[str, Any]:
        object_handle = dict(self.object_handle) if isinstance(self.object_handle, dict) else None
        reference = (
            object_handle.get("reference")
            if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
            else {}
        )
        object_metadata = (
            object_handle.get("metadata")
            if isinstance(object_handle, dict) and isinstance(object_handle.get("metadata"), dict)
            else {}
        )
        metadata = dict(self.metadata)
        provider_name = (
            self.provider_name
            or metadata.get("provider_name")
            or metadata.get("storage_provider_name")
            or object_metadata.get("provider_name")
            or reference.get("provider_name")
        )
        provider_type = (
            self.provider_type
            or metadata.get("provider_type")
            or metadata.get("storage_provider_type")
            or object_metadata.get("provider_type")
            or reference.get("provider_type")
        )
        if provider_type in {None, "", "null"} and provider_name in {"memory", "filesystem"}:
            provider_type = provider_name
        return {
            "storage_execution_verification_descriptor_schema_version": "1",
            "verification_id": self.verification_id,
            "request_id": self.request_id,
            "artifact_id": self.artifact_id,
            "upload_session_id": self.upload_session_id,
            "execution_session_id": self.execution_session_id,
            "requested_operation": self.requested_operation,
            "verification_status": self.verification_status,
            "verification_required": self.verification_required,
            "verification_available": self.verification_available,
            "storage_verified": self.storage_verified,
            "object_exists": self.object_exists,
            "object_stored": self.object_stored,
            "file_uploaded": self.file_uploaded,
            "checksum_calculated": self.checksum_calculated,
            "provider_name": provider_name,
            "provider_type": provider_type,
            "storage_provider_name": provider_name,
            "storage_provider_type": provider_type,
            "provider_configured": self.provider_configured,
            "object_handle": object_handle,
            "checksum": self.checksum,
            "content_length": self.content_length,
            "content_type": self.content_type,
            "metadata": metadata,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "persistence_status": self.persistence_status,
        }


@dataclass(frozen=True)
class StorageExecutionResultDescriptor:
    result_id: str | None
    request_id: str | None
    verification_id: str | None
    artifact_id: str | None
    upload_session_id: str | None
    execution_session_id: str | None
    requested_operation: str | None
    result_status: str
    execution_started: bool
    execution_completed: bool
    execution_succeeded: bool
    execution_failed: bool
    operation_invoked: bool
    real_storage_operations_enabled: bool
    provider_name: str | None
    provider_type: str | None
    provider_configured: bool
    object_handle: dict[str, Any] | None
    object_stored: bool
    object_exists: bool
    file_uploaded: bool
    checksum_calculated: bool
    checksum: str | None
    content_length: int | None
    content_type: str | None
    error_code: str | None
    error_message: str | None
    blocking_issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    persistence_status: str

    def as_dict(self) -> dict[str, Any]:
        object_handle = dict(self.object_handle) if isinstance(self.object_handle, dict) else None
        reference = (
            object_handle.get("reference")
            if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
            else {}
        )
        object_metadata = (
            object_handle.get("metadata")
            if isinstance(object_handle, dict) and isinstance(object_handle.get("metadata"), dict)
            else {}
        )
        provider_name = self.provider_name or object_metadata.get("provider_name") or reference.get("provider_name")
        provider_type = self.provider_type or object_metadata.get("provider_type") or reference.get("provider_type")
        if provider_type in {None, "", "null"} and provider_name in {"memory", "filesystem"}:
            provider_type = provider_name
        return {
            "storage_execution_result_descriptor_schema_version": "1",
            "result_id": self.result_id,
            "request_id": self.request_id,
            "verification_id": self.verification_id,
            "artifact_id": self.artifact_id,
            "upload_session_id": self.upload_session_id,
            "execution_session_id": self.execution_session_id,
            "requested_operation": self.requested_operation,
            "result_status": self.result_status,
            "execution_started": self.execution_started,
            "execution_completed": self.execution_completed,
            "execution_succeeded": self.execution_succeeded,
            "execution_failed": self.execution_failed,
            "operation_invoked": self.operation_invoked,
            "real_storage_operations_enabled": self.real_storage_operations_enabled,
            "provider_name": provider_name,
            "provider_type": provider_type,
            "storage_provider_name": provider_name,
            "storage_provider_type": provider_type,
            "provider_configured": self.provider_configured,
            "object_handle": object_handle,
            "object_stored": self.object_stored,
            "object_exists": self.object_exists,
            "file_uploaded": self.file_uploaded,
            "checksum_calculated": self.checksum_calculated,
            "checksum": self.checksum,
            "content_length": self.content_length,
            "content_type": self.content_type,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "blocking_issues": list(self.blocking_issues),
            "warnings": list(self.warnings),
            "persistence_status": self.persistence_status,
        }


def _execution_session_id(*, artifact_id: str | None) -> str | None:
    if not artifact_id:
        return None
    return f"storage-execution-session:{artifact_id}"


def _normalize_requested_operation(operation: str | None) -> str | None:
    if not isinstance(operation, str):
        return None
    normalized = operation.strip().lower().replace("-", "_")
    aliases = {
        "create": "create_object",
        "upload": "upload_object",
        "replace": "replace_object",
        "delete": "delete_object",
        "download": "download_object",
        "get": "get_object",
        "head": "head_object",
        "verify": "verify_object",
    }
    return aliases.get(normalized, normalized)


def _stable_request_id(
    *,
    artifact_id: str | None,
    execution_session_id: str | None,
    requested_operation: str | None,
    idempotency_key: str | None,
) -> str:
    seed = "|".join(
        [
            artifact_id or "artifact:unknown",
            execution_session_id or "execution-session:unknown",
            requested_operation or "operation:unknown",
            idempotency_key or "idempotency:not-supplied",
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"storage-execution-request:{digest}"


def _stable_verification_id(
    *,
    request_id: str | None,
    artifact_id: str | None,
    execution_session_id: str | None,
) -> str:
    seed = "|".join(
        [
            request_id or "request:unknown",
            artifact_id or "artifact:unknown",
            execution_session_id or "execution-session:unknown",
            "verification:not-executed",
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"storage-execution-verification:{digest}"


def _stable_result_id(
    *,
    request_id: str | None,
    verification_id: str | None,
    artifact_id: str | None,
    execution_session_id: str | None,
) -> str:
    seed = "|".join(
        [
            request_id or "request:unknown",
            verification_id or "verification:unknown",
            artifact_id or "artifact:unknown",
            execution_session_id or "execution-session:unknown",
            "result:not-executed",
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"storage-execution-result:{digest}"


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


def _provider_descriptor(upload_session: dict[str, Any]) -> dict[str, Any]:
    descriptor = upload_session.get("storage_provider_descriptor")
    if isinstance(descriptor, dict) and descriptor:
        return descriptor
    storage_plan = upload_session.get("storage_operation_plan") or {}
    descriptor = storage_plan.get("provider_descriptor")
    if isinstance(descriptor, dict) and descriptor:
        return descriptor
    flags = upload_session.get("execution_flags") or {}
    return {
        "provider_name": flags.get("storage_provider_name") or "null",
        "provider_type": flags.get("storage_provider_type") or "null",
        "configured": bool(flags.get("storage_provider_configured")),
        "status": flags.get("storage_provider_status") or "storage_not_configured",
        "capabilities": [],
        "missing_configuration_reason": "storage_not_configured",
        "required_configuration_keys": [],
        "safe_configuration_fingerprint": None,
        "metadata": {},
    }


def _normalize_provider_descriptor(provider_descriptor: dict[str, Any] | None) -> dict[str, Any]:
    descriptor = dict(provider_descriptor or {})
    metadata = descriptor.get("metadata") if isinstance(descriptor.get("metadata"), dict) else {}
    safe_configuration = (
        metadata.get("safe_configuration") if isinstance(metadata.get("safe_configuration"), dict) else {}
    )

    provider_name = (
        descriptor.get("provider_name")
        or descriptor.get("name")
        or descriptor.get("storage_provider_name")
        or descriptor.get("provider")
        or metadata.get("provider_name")
        or metadata.get("storage_provider_name")
        or safe_configuration.get("provider_name")
        or safe_configuration.get("storage_provider_name")
    )
    provider_type = (
        descriptor.get("provider_type")
        or descriptor.get("type")
        or descriptor.get("storage_provider_type")
        or metadata.get("provider_type")
        or metadata.get("storage_provider_type")
        or safe_configuration.get("provider_type")
        or safe_configuration.get("storage_provider_type")
    )

    if provider_type in {None, "", "null"} and provider_name in {"memory", "filesystem"}:
        provider_type = provider_name
    if provider_name in {None, "", "null"} and provider_type in {"memory", "filesystem"}:
        provider_name = provider_type

    descriptor["provider_name"] = provider_name
    descriptor["provider_type"] = provider_type
    descriptor["storage_provider_name"] = provider_name
    descriptor["storage_provider_type"] = provider_type

    return descriptor


def _runtime_operation_from_trace(runtime_trace: dict[str, Any], operation: str) -> dict[str, Any] | None:
    operations = runtime_trace.get("operations")
    normalized_operation = STORAGE_EXECUTION_OPERATION_MAP[operation]
    if isinstance(operations, dict):
        return operations.get(normalized_operation)
    return None


def _operation_capability(provider_descriptor: dict[str, Any], operation: str) -> dict[str, Any]:
    normalized_operation = STORAGE_EXECUTION_OPERATION_MAP[operation]
    for capability in provider_descriptor.get("capabilities") or []:
        if capability.get("operation") == normalized_operation:
            return dict(capability)
    return {
        "operation": normalized_operation,
        "supported": False,
        "configured": bool(provider_descriptor.get("configured")),
        "status": provider_descriptor.get("status") or "storage_not_configured",
        "reason": "operation_not_declared",
    }


def _operation_entry(
    *,
    operation: str,
    provider_descriptor: dict[str, Any],
    runtime_trace: dict[str, Any],
    storage_configured: bool,
) -> dict[str, Any]:
    capability = _operation_capability(provider_descriptor, operation)
    planned_request = _runtime_operation_from_trace(runtime_trace, operation)
    if not storage_configured:
        provider_readiness_state = STORAGE_OPERATION_STATE_NOT_CONFIGURED
        state = STORAGE_OPERATION_STATE_BLOCKED
        reason = (
            provider_descriptor.get("missing_configuration_reason")
            or provider_descriptor.get("status")
            or "storage_not_configured"
        )
        required_next_step = "configure_storage_provider"
    elif not capability.get("supported"):
        provider_readiness_state = STORAGE_OPERATION_STATE_BLOCKED
        state = STORAGE_OPERATION_STATE_BLOCKED
        reason = "provider_capability_not_supported"
        required_next_step = f"enable_{STORAGE_EXECUTION_OPERATION_MAP[operation]}_capability"
    elif not capability.get("configured"):
        provider_readiness_state = STORAGE_OPERATION_STATE_BLOCKED
        state = STORAGE_OPERATION_STATE_BLOCKED
        reason = capability.get("status") or "provider_capability_not_configured"
        required_next_step = f"configure_{STORAGE_EXECUTION_OPERATION_MAP[operation]}_capability"
    else:
        provider_readiness_state = STORAGE_OPERATION_STATE_FUTURE_READY
        state = STORAGE_EXECUTION_STATE_PLANNED
        reason = "real_storage_execution_not_enabled"
        required_next_step = "enable_storage_execution_gateway"
    return {
        "operation": operation,
        "provider_operation": STORAGE_EXECUTION_OPERATION_MAP[operation],
        "state": state,
        "provider_readiness_state": provider_readiness_state,
        "status": state,
        "execution_allowed": False,
        "operation_invoked": False,
        "real_storage_operations_enabled": False,
        "reason": reason,
        "required_next_step": required_next_step,
        "capability": capability,
        "planned_request": planned_request,
    }


def build_storage_execution_plan(upload_session: dict[str, Any]) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(_provider_descriptor(upload_session))
    runtime_trace = upload_session.get("runtime_trace") if isinstance(upload_session.get("runtime_trace"), dict) else {}
    storage_configured = bool(provider_descriptor.get("configured"))
    operations = [
        _operation_entry(
            operation=operation,
            provider_descriptor=provider_descriptor,
            runtime_trace=runtime_trace,
            storage_configured=storage_configured,
        )
        for operation in STORAGE_EXECUTION_OPERATIONS
    ]
    return {
        "storage_execution_plan_schema_version": "1",
        "planning_mode": STORAGE_EXECUTION_MODE_READINESS_ONLY,
        "operation_order": list(STORAGE_EXECUTION_OPERATIONS),
        "operations": operations,
        "default_operation": "upload_object",
        "storage_configured": storage_configured,
        "gateway_authoritative": True,
        "real_storage_operations_enabled": False,
        "required_first_step": "configure_storage_provider"
        if not storage_configured
        else "enable_storage_execution_gateway",
    }


def validate_storage_execution_session(
    *,
    upload_session: dict[str, Any],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(_provider_descriptor(upload_session))
    runtime_trace = upload_session.get("runtime_trace") if isinstance(upload_session.get("runtime_trace"), dict) else {}
    flags = upload_session.get("execution_flags") or {}
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not upload_session.get("artifact_id"):
        blocking_issues.append(
            _issue("artifact_id_missing", "Storage execution requires an artifact_id.", component="storage_execution")
        )
    if not upload_session.get("upload_session_id"):
        blocking_issues.append(
            _issue(
                "upload_session_missing", "Storage execution requires an upload_session_id.", component="upload_session"
            )
        )
    if not provider_descriptor:
        blocking_issues.append(
            _issue(
                "provider_descriptor_missing",
                "Storage execution requires a provider descriptor.",
                component="storage_provider",
            )
        )
    if not provider_descriptor.get("configured"):
        blocking_issues.append(
            _issue(
                "storage_provider_not_configured",
                "Storage provider is not configured for execution.",
                component="storage_provider",
            )
        )
    unsupported_operations = [
        operation
        for operation in execution_plan.get("operations") or []
        if operation.get("state") == STORAGE_OPERATION_STATE_BLOCKED
        and operation.get("reason") == "provider_capability_not_supported"
    ]
    for operation in unsupported_operations:
        blocking_issues.append(
            _issue(
                "storage_operation_not_supported",
                "Storage provider does not support the planned operation.",
                component="storage_operation",
                item_id=operation.get("operation"),
            )
        )
    blocked_operations = [
        operation
        for operation in execution_plan.get("operations") or []
        if operation.get("status") == STORAGE_EXECUTION_STATE_BLOCKED
    ]
    for operation in blocked_operations:
        if operation.get("reason") == "provider_capability_not_supported":
            continue
        blocking_issues.append(
            _issue(
                "storage_operation_blocked",
                "Storage operation is currently blocked.",
                component="storage_operation",
                item_id=operation.get("operation"),
            )
        )
    if flags.get("object_stored"):
        warnings.append(
            _issue(
                "object_already_marked_stored",
                "Upload session reports object_stored=true before the storage execution gateway is enabled.",
                component="storage_execution",
                severity="warning",
            )
        )
    if flags.get("file_uploaded"):
        warnings.append(
            _issue(
                "file_already_marked_uploaded",
                "Upload session reports file_uploaded=true before the storage execution gateway is enabled.",
                component="binary_upload",
                severity="warning",
            )
        )
    if flags.get("checksum_calculated"):
        warnings.append(
            _issue(
                "checksum_already_marked",
                "Upload session reports checksum_calculated=true before real binary content is available.",
                component="binary_upload",
                severity="warning",
            )
        )
    if flags.get("ingestion_executed"):
        blocking_issues.append(
            _issue(
                "ingestion_must_remain_blocked",
                "Ingestion must remain blocked until storage is verified.",
                component="processing_handoff",
            )
        )
    if runtime_trace.get("operation_invoked"):
        warnings.append(
            _issue(
                "runtime_operation_invoked",
                "Runtime trace reports an invoked storage operation; gateway remains read-only in this foundation.",
                component="storage_runtime",
                severity="warning",
            )
        )
    if not execution_plan.get("operations"):
        blocking_issues.append(
            _issue(
                "execution_plan_empty",
                "Storage execution plan does not contain operations.",
                component="storage_execution",
            )
        )
    return {
        "validation_status": "blocked" if blocking_issues else "planned",
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def build_storage_execution_runtime_trace(
    *,
    upload_session: dict[str, Any],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    upload_runtime_trace = (
        upload_session.get("runtime_trace") if isinstance(upload_session.get("runtime_trace"), dict) else {}
    )
    provider_descriptor = _normalize_provider_descriptor(_provider_descriptor(upload_session))
    return {
        "storage_execution_runtime_trace_schema_version": "1",
        "gateway": "storage_execution_gateway",
        "execution_prepared": True,
        "execution_allowed": False,
        "operation_invoked": False,
        "real_storage_operations_enabled": False,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "provider_configured": bool(provider_descriptor.get("configured")),
        "provider_status": provider_descriptor.get("status"),
        "upload_runtime_state": upload_session.get("runtime_state"),
        "upload_runtime_trace": upload_runtime_trace,
        "planned_operations": {
            item["operation"]: {
                "state": item["state"],
                "status": item["status"],
                "required_next_step": item["required_next_step"],
                "provider_operation": item["provider_operation"],
            }
            for item in execution_plan.get("operations") or []
        },
        "runtime_adapter_state_model": {
            "not_configured": STORAGE_OPERATION_STATE_NOT_CONFIGURED,
            "blocked": STORAGE_OPERATION_STATE_BLOCKED,
            "future_ready": STORAGE_OPERATION_STATE_FUTURE_READY,
        },
    }


def build_storage_execution_next_available_actions(
    *,
    execution_plan: dict[str, Any],
    validation_result: dict[str, Any],
) -> list[dict[str, Any]]:
    validation_blocked = bool(validation_result.get("blocking_issues"))
    actions: list[dict[str, Any]] = []
    for operation in execution_plan.get("operations") or []:
        actions.append(
            {
                "action": operation["operation"],
                "available": False,
                "status": "blocked" if validation_blocked or operation["status"] == "blocked" else "planned",
                "reason": operation["reason"],
                "required_next_step": operation["required_next_step"],
                "operation_invoked": False,
                "real_storage_operations_enabled": False,
            }
        )
    return actions


def build_storage_execution_validation_summary(validation_result: dict[str, Any]) -> dict[str, Any]:
    blocking_issues = validation_result.get("blocking_issues") or []
    warnings = validation_result.get("warnings") or []
    return {
        "validation_status": validation_result.get("validation_status")
        or ("blocked" if blocking_issues else "planned"),
        "blocking_issue_count": len(blocking_issues),
        "warning_count": len(warnings),
        "blocked": bool(blocking_issues),
        "executable": False,
        "real_storage_operations_enabled": False,
    }


def _operation_by_name(execution_plan: dict[str, Any], operation_name: str) -> dict[str, Any] | None:
    for operation in execution_plan.get("operations") or []:
        if operation.get("operation") == operation_name:
            return operation
    return None


def _action_entry(
    *,
    action: str,
    execution_plan: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    operation = _operation_by_name(execution_plan, STORAGE_EXECUTION_ACTION_OPERATION_MAP[action])
    validation_blocked = bool(validation_summary.get("blocked"))
    operation_status = operation.get("status") if operation else STORAGE_EXECUTION_STATE_BLOCKED
    status = (
        STORAGE_EXECUTION_STATE_BLOCKED
        if validation_blocked or operation_status == STORAGE_EXECUTION_STATE_BLOCKED
        else STORAGE_EXECUTION_STATE_PLANNED
    )
    reason = (
        "storage_execution_validation_blocked"
        if validation_blocked
        else (operation or {}).get("reason") or "storage_execution_prepare_only"
    )
    required_next_step = (
        (operation or {}).get("required_next_step")
        or execution_plan.get("required_first_step")
        or "configure_storage_provider"
    )
    if action in {"mark_storage_verified", "handoff_to_processing"}:
        status = STORAGE_EXECUTION_STATE_BLOCKED
        reason = "storage_not_verified"
        required_next_step = "execute_storage_before_processing_handoff"
    return {
        "action": action,
        "operation": STORAGE_EXECUTION_ACTION_OPERATION_MAP[action],
        "available": False,
        "execution_allowed": False,
        "operation_invoked": False,
        "real_storage_operations_enabled": False,
        "status": status,
        "reason": reason,
        "required_next_step": required_next_step,
    }


def build_storage_execution_action_model(
    *,
    execution_plan: dict[str, Any],
    validation_result: dict[str, Any],
) -> dict[str, Any]:
    validation_summary = build_storage_execution_validation_summary(validation_result)
    actions = [
        _action_entry(
            action=action,
            execution_plan=execution_plan,
            validation_summary=validation_summary,
        )
        for action in STORAGE_EXECUTION_ACTIONS
    ]
    return {
        "storage_execution_action_model_schema_version": "1",
        "execution_mode": "prepare_only",
        "actions": actions,
        "prepare_actions": [action for action in actions if action["action"].startswith("prepare_")],
        "verification_actions": [
            action for action in actions if action["action"] in {"verify_object", "mark_storage_verified"}
        ],
        "processing_handoff_actions": [action for action in actions if action["action"] == "handoff_to_processing"],
        "executable": False,
        "verification_required": True,
        "processing_handoff_allowed": False,
        "real_storage_operations_enabled": False,
    }


def build_storage_execution_session(upload_session: dict[str, Any]) -> StorageExecutionSession:
    provider_descriptor = _normalize_provider_descriptor(_provider_descriptor(upload_session))
    execution_plan = build_storage_execution_plan(upload_session)
    validation_result = validate_storage_execution_session(
        upload_session=upload_session,
        execution_plan=execution_plan,
    )
    runtime_trace = build_storage_execution_runtime_trace(
        upload_session=upload_session,
        execution_plan=execution_plan,
    )
    execution_state = (
        STORAGE_EXECUTION_STATE_BLOCKED if validation_result["blocking_issues"] else STORAGE_EXECUTION_STATE_PLANNED
    )
    return StorageExecutionSession(
        execution_session_id=_execution_session_id(artifact_id=upload_session.get("artifact_id")),
        upload_session_id=upload_session.get("upload_session_id"),
        artifact_id=upload_session.get("artifact_id"),
        provider_descriptor=provider_descriptor,
        operation=execution_plan["default_operation"],
        execution_state=execution_state,
        execution_plan=execution_plan,
        validation_result=validation_result,
        runtime_trace=runtime_trace,
        next_available_actions=build_storage_execution_next_available_actions(
            execution_plan=execution_plan,
            validation_result=validation_result,
        ),
    )


def serialize_storage_execution_session(session: StorageExecutionSession) -> dict[str, Any]:
    return {
        "storage_execution_session_schema_version": STORAGE_EXECUTION_SESSION_SCHEMA_VERSION,
        "execution_session_id": session.execution_session_id,
        "upload_session_id": session.upload_session_id,
        "artifact_id": session.artifact_id,
        "provider_descriptor": session.provider_descriptor,
        "operation": session.operation,
        "execution_state": session.execution_state,
        "execution_plan": session.execution_plan,
        "validation_result": session.validation_result,
        "runtime_trace": session.runtime_trace,
        "next_available_actions": session.next_available_actions,
    }


def build_prepared_storage_execution(upload_session: dict[str, Any]) -> dict[str, Any]:
    storage_execution_session = serialize_storage_execution_session(build_storage_execution_session(upload_session))
    validation = storage_execution_session["validation_result"]
    validation_summary = build_storage_execution_validation_summary(validation)
    action_model = build_storage_execution_action_model(
        execution_plan=storage_execution_session["execution_plan"],
        validation_result=validation,
    )
    return {
        "prepared": True,
        "prepare_available": True,
        "executable": False,
        "verification_required": True,
        "processing_handoff_allowed": False,
        "processing_blocked_reason": "storage_not_verified",
        "prepared_execution": {
            "execution_session_id": storage_execution_session["execution_session_id"],
            "artifact_id": storage_execution_session["artifact_id"],
            "upload_session_id": storage_execution_session["upload_session_id"],
            "operation": storage_execution_session["operation"],
            "execution_state": storage_execution_session["execution_state"],
            "prepared": True,
            "executable": False,
            "operation_invoked": False,
            "real_storage_operations_enabled": False,
        },
        "storage_execution_session": storage_execution_session,
        "execution_plan": storage_execution_session["execution_plan"],
        "validation": validation,
        "validation_summary": validation_summary,
        "action_model": action_model,
        "provider_descriptor": storage_execution_session["provider_descriptor"],
        "runtime_trace": storage_execution_session["runtime_trace"],
        "next_available_actions": storage_execution_session["next_available_actions"],
    }


def _request_issue(
    *,
    code: str,
    message: str,
    item_id: str | None = None,
) -> dict[str, Any]:
    return _issue(
        code,
        message,
        component="storage_execution_request",
        item_id=item_id,
    )


def _request_operation_entry(
    *,
    prepared_execution: dict[str, Any],
    requested_operation: str | None,
) -> dict[str, Any] | None:
    if not requested_operation:
        return None
    for operation in prepared_execution["execution_plan"].get("operations") or []:
        if operation.get("operation") == requested_operation:
            return operation
    return None


def _request_action_entry(
    *,
    prepared_execution: dict[str, Any],
    requested_operation: str | None,
) -> dict[str, Any] | None:
    if not requested_operation:
        return None
    for action in prepared_execution["action_model"].get("actions") or []:
        if action.get("operation") == requested_operation:
            return action
    return None


def _storage_descriptor_for_operation(operation_entry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(operation_entry, dict):
        return {}
    planned_request = operation_entry.get("planned_request")
    if isinstance(planned_request, dict) and isinstance(planned_request.get("descriptor"), dict):
        return planned_request["descriptor"]
    return {}


def _resolve_memory_object_handle(
    *,
    storage_provider: Any,
    upload_session: dict[str, Any],
    request_metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    request_metadata = dict(request_metadata or {})
    request_handle = request_metadata.get("object_handle")
    if isinstance(request_handle, dict) and request_handle:
        return dict(request_handle), "request_metadata"
    if isinstance(request_handle, str) and request_handle.strip():
        return {"object_handle": request_handle.strip()}, "request_metadata"
    latest_object = (
        storage_provider.latest_object_for_artifact(upload_session.get("artifact_id"))
        if hasattr(storage_provider, "latest_object_for_artifact")
        else None
    )
    latest_handle = latest_object.get("object_handle") if isinstance(latest_object, dict) else None
    if isinstance(latest_handle, dict) and latest_handle:
        return dict(latest_handle), "latest_object_for_artifact"
    return None, "missing"


def _provider_configuration_from_descriptor(
    provider_descriptor: dict[str, Any], object_handle: dict[str, Any] | None = None
) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(provider_descriptor)
    metadata = provider_descriptor.get("metadata") if isinstance(provider_descriptor.get("metadata"), dict) else {}
    safe_configuration = (
        metadata.get("safe_configuration") if isinstance(metadata.get("safe_configuration"), dict) else {}
    )
    reference = (
        object_handle.get("reference")
        if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
        else {}
    )
    return {
        **safe_configuration,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        **({"storage_root": metadata.get("storage_root")} if metadata.get("storage_root") else {}),
        **({"storage_root": reference.get("storage_root")} if reference.get("storage_root") else {}),
    }


def _resolve_concrete_storage_provider(
    provider_descriptor: dict[str, Any], object_handle: dict[str, Any] | None = None
) -> Any:
    provider_descriptor = _normalize_provider_descriptor(provider_descriptor)
    provider_name = provider_descriptor.get("provider_name")
    provider_type = provider_descriptor.get("provider_type")
    configuration = _provider_configuration_from_descriptor(provider_descriptor, object_handle)
    return get_storage_provider_registry().resolve(
        provider_type or provider_name,
        configuration=configuration,
    )


def _is_executable_storage_provider(provider_descriptor: dict[str, Any]) -> bool:
    provider_descriptor = _normalize_provider_descriptor(provider_descriptor)
    provider_name = provider_descriptor.get("provider_name")
    provider_type = provider_descriptor.get("provider_type")
    return provider_name in {"memory", "filesystem"} or provider_type in {"memory", "filesystem"}


def _is_executable_provider_type(provider_type: Any) -> bool:
    return provider_type in {"memory", "filesystem"}


def _content_from_request_metadata(
    request_metadata: dict[str, Any] | None,
) -> tuple[bytes | None, list[dict[str, Any]]]:
    request_metadata = dict(request_metadata or {})
    warnings: list[dict[str, Any]] = []
    content_value = None
    if "content_bytes" in request_metadata:
        content_bytes = request_metadata.get("content_bytes")
        if isinstance(content_bytes, bytes):
            content_value = content_bytes
        elif isinstance(content_bytes, str):
            try:
                content_value = base64.b64decode(content_bytes, validate=True)
            except Exception:
                content_value = content_bytes.encode("utf-8")
    elif "content_text" in request_metadata:
        content_text = request_metadata.get("content_text")
        if isinstance(content_text, str):
            content_value = content_text.encode("utf-8")
    elif "content" in request_metadata:
        content = request_metadata.get("content")
        if isinstance(content, bytes):
            content_value = content
        elif isinstance(content, str):
            content_value = content.encode("utf-8")
    if content_value is None:
        warnings.append(
            _issue(
                "upload_content_empty",
                "Storage upload request did not include content; an empty payload will be uploaded.",
                component="storage_execution_request",
                severity="warning",
            )
        )
        return b"", warnings
    return content_value, warnings


def _public_memory_operation_result(
    runtime_operation: dict[str, Any], requested_operation: str | None
) -> dict[str, Any]:
    result = runtime_operation.get("result") if isinstance(runtime_operation.get("result"), dict) else {}
    provider_descriptor = _normalize_provider_descriptor(
        result.get("provider") if isinstance(result.get("provider"), dict) else {}
    )
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    metadata = dict(metadata)
    operation_request = (
        metadata.get("operation_request") if isinstance(metadata.get("operation_request"), dict) else None
    )
    if operation_request:
        descriptor = (
            operation_request.get("descriptor") if isinstance(operation_request.get("descriptor"), dict) else {}
        )
        sanitized_descriptor = {
            key: value for key, value in descriptor.items() if key not in {"content", "content_bytes", "content_text"}
        }
        operation_request = {
            **operation_request,
            "descriptor": sanitized_descriptor,
            "payload_included": False,
        }
        metadata["operation_request"] = operation_request
    if requested_operation in {"get_object", "download_object"} and "content" in metadata:
        metadata = {
            **metadata,
            "content_available": metadata.get("content") is not None,
            "content_returned": False,
        }
        metadata.pop("content", None)
    result = {
        **result,
        "provider": provider_descriptor,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "metadata": metadata,
    }
    request = runtime_operation.get("request") if isinstance(runtime_operation.get("request"), dict) else None
    if request:
        descriptor = request.get("descriptor") if isinstance(request.get("descriptor"), dict) else {}
        request = {
            **request,
            "descriptor": {
                key: value
                for key, value in descriptor.items()
                if key not in {"content", "content_bytes", "content_text"}
            },
            "payload_included": False,
        }

    return {
        **runtime_operation,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "request": request,
        "result": result,
    }


def _memory_storage_verification_issues(
    *,
    provider_descriptor: dict[str, Any],
    operation_metadata: dict[str, Any],
    object_handle: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    provider_is_executable = _is_executable_storage_provider(provider_descriptor)
    checks = {
        "executable_provider_required": provider_is_executable,
        "object_handle_required": bool(object_handle),
        "object_exists_required": bool(operation_metadata.get("object_exists")),
        "object_stored_required": bool(operation_metadata.get("object_stored")),
        "file_uploaded_required": bool(operation_metadata.get("file_uploaded")),
        "checksum_calculated_required": bool(operation_metadata.get("checksum_calculated")),
        "checksum_required": bool(operation_metadata.get("checksum")),
        "content_length_required": isinstance(operation_metadata.get("content_length"), int)
        and operation_metadata.get("content_length") >= 0,
        "object_not_deleted_required": not bool(operation_metadata.get("deleted")),
    }
    messages = {
        "executable_provider_required": "Storage verification requires an executable concrete provider.",
        "object_handle_required": "Storage verification requires an object_handle.",
        "object_exists_required": "Storage verification requires an existing object.",
        "object_stored_required": "Storage verification requires object_stored=true.",
        "file_uploaded_required": "Storage verification requires file_uploaded=true.",
        "checksum_calculated_required": "Storage verification requires checksum_calculated=true.",
        "checksum_required": "Storage verification requires a checksum.",
        "content_length_required": "Storage verification requires content_length >= 0.",
        "object_not_deleted_required": "Storage verification cannot pass for a deleted object.",
    }
    for code, passed in checks.items():
        if not passed:
            blocking_issues.append(
                _issue(
                    code,
                    messages[code],
                    component="storage_execution_verification",
                )
            )
    if operation_metadata.get("content_length") == 0:
        warnings.append(
            _issue(
                "verified_object_empty",
                "Storage verification passed for an empty object.",
                component="storage_execution_verification",
                severity="warning",
            )
        )
    return blocking_issues, warnings


def _verification_result_from_memory_head(
    *,
    runtime_operation: dict[str, Any] | None,
    provider_descriptor: dict[str, Any],
    object_handle: dict[str, Any] | None,
    resolution_source: str,
) -> dict[str, Any]:
    storage_operation_result = (
        runtime_operation.get("result")
        if isinstance(runtime_operation, dict) and isinstance(runtime_operation.get("result"), dict)
        else {}
    )
    operation_metadata = (
        storage_operation_result.get("metadata") if isinstance(storage_operation_result.get("metadata"), dict) else {}
    )
    blocking_issues, warnings = _memory_storage_verification_issues(
        provider_descriptor=provider_descriptor,
        operation_metadata=operation_metadata,
        object_handle=object_handle,
    )
    storage_verified = not blocking_issues
    return {
        "verification_result_schema_version": "1",
        "verification_status": "storage_verified" if storage_verified else "verification_failed",
        "verification_available": isinstance(runtime_operation, dict),
        "storage_verified": storage_verified,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "object_handle": storage_operation_result.get("object_handle")
        if isinstance(storage_operation_result.get("object_handle"), dict)
        else object_handle,
        "object_handle_resolution_source": resolution_source,
        "object_exists": bool(operation_metadata.get("object_exists")),
        "object_stored": bool(operation_metadata.get("object_stored")),
        "file_uploaded": bool(operation_metadata.get("file_uploaded")),
        "checksum_calculated": bool(operation_metadata.get("checksum_calculated")),
        "checksum": operation_metadata.get("checksum"),
        "content_length": operation_metadata.get("content_length"),
        "content_type": operation_metadata.get("content_type"),
        "deleted": bool(operation_metadata.get("deleted")),
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
        "provider_descriptor": provider_descriptor,
    }


def _execute_memory_verify_object(
    *,
    upload_session: dict[str, Any],
    prepared_execution: dict[str, Any],
    operation_entry: dict[str, Any] | None,
    validation: dict[str, Any],
    request_metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if validation.get("blocking_issues"):
        return None, None, blocking_issues, warnings
    provider_descriptor = (
        prepared_execution.get("provider_descriptor")
        if isinstance(prepared_execution.get("provider_descriptor"), dict)
        else {}
    )
    if not _is_executable_storage_provider(provider_descriptor):
        return None, None, blocking_issues, warnings
    request_metadata = dict(request_metadata or {})
    request_handle = (
        request_metadata.get("object_handle") if isinstance(request_metadata.get("object_handle"), dict) else None
    )
    storage_provider = _resolve_concrete_storage_provider(provider_descriptor, request_handle)
    if storage_provider.descriptor.provider_type not in {"memory", "filesystem"}:
        return None, None, blocking_issues, warnings
    provider_descriptor = storage_provider.descriptor.as_dict()
    object_handle, resolution_source = _resolve_memory_object_handle(
        storage_provider=storage_provider,
        upload_session=upload_session,
        request_metadata=request_metadata,
    )
    if object_handle is None:
        blocking_issues.append(
            _request_issue(
                code="object_handle_required",
                message="Storage verification requires an object_handle or an existing object for the artifact.",
                item_id="verify_object",
            )
        )
        return None, None, blocking_issues, warnings
    storage_descriptor = {
        **_storage_descriptor_for_operation(operation_entry),
        **request_metadata,
        "artifact_id": upload_session.get("artifact_id"),
        "upload_session_id": upload_session.get("upload_session_id"),
        "document_record_id": upload_session.get("document_record_id"),
        "document_version_id": upload_session.get("document_version_id"),
        "requested_by": upload_session.get("requested_by"),
        "object_handle": object_handle,
        "object_handle_resolution_source": resolution_source,
    }
    runtime_operation = get_storage_provider_runtime_adapter().build_operation(
        storage_provider=storage_provider,
        operation="head_object",
        storage_descriptor=storage_descriptor,
        execute=True,
    )
    runtime_operation_dict = runtime_operation.as_dict()
    public_operation = _public_memory_operation_result(runtime_operation_dict, "verify_object")
    verification_result = _verification_result_from_memory_head(
        runtime_operation=public_operation,
        provider_descriptor=provider_descriptor,
        object_handle=object_handle,
        resolution_source=resolution_source,
    )
    return (
        public_operation,
        verification_result,
        verification_result["blocking_issues"],
        verification_result["warnings"],
    )


def _execute_memory_storage_operation(
    *,
    upload_session: dict[str, Any],
    prepared_execution: dict[str, Any],
    operation_entry: dict[str, Any] | None,
    validation: dict[str, Any],
    requested_operation: str | None,
    request_metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    executable_operations = {"create_object", "upload_object", "head_object", "get_object", "delete_object"}
    if requested_operation not in executable_operations:
        return None, blocking_issues, warnings
    if validation.get("blocking_issues"):
        return None, blocking_issues, warnings
    provider_descriptor = (
        prepared_execution.get("provider_descriptor")
        if isinstance(prepared_execution.get("provider_descriptor"), dict)
        else {}
    )
    if not _is_executable_storage_provider(provider_descriptor):
        return None, blocking_issues, warnings
    request_metadata = dict(request_metadata or {})
    request_handle = (
        request_metadata.get("object_handle") if isinstance(request_metadata.get("object_handle"), dict) else None
    )
    storage_provider = _resolve_concrete_storage_provider(provider_descriptor, request_handle)
    if storage_provider.descriptor.provider_type not in {"memory", "filesystem"}:
        return None, blocking_issues, warnings
    object_handle, resolution_source = _resolve_memory_object_handle(
        storage_provider=storage_provider,
        upload_session=upload_session,
        request_metadata=request_metadata,
    )
    if requested_operation != "create_object" and object_handle is None:
        blocking_issues.append(
            _request_issue(
                code="object_handle_required",
                message="Storage operation requires an object_handle or an existing object for the artifact.",
                item_id=requested_operation,
            )
        )
        return None, blocking_issues, warnings
    storage_descriptor = {
        **_storage_descriptor_for_operation(operation_entry),
        **request_metadata,
        "artifact_id": upload_session.get("artifact_id"),
        "upload_session_id": upload_session.get("upload_session_id"),
        "document_record_id": upload_session.get("document_record_id"),
        "document_version_id": upload_session.get("document_version_id"),
        "requested_by": upload_session.get("requested_by"),
        "object_handle": object_handle,
        "object_handle_resolution_source": resolution_source,
    }
    if requested_operation == "upload_object":
        content, content_warnings = _content_from_request_metadata(request_metadata)
        storage_descriptor["content"] = content
        warnings.extend(content_warnings)
    provider_operation = "get_object" if requested_operation == "download_object" else requested_operation
    runtime_operation = get_storage_provider_runtime_adapter().build_operation(
        storage_provider=storage_provider,
        operation=provider_operation,
        storage_descriptor=storage_descriptor,
        execute=True,
    )
    runtime_operation_dict = runtime_operation.as_dict()
    return _public_memory_operation_result(runtime_operation_dict, requested_operation), blocking_issues, warnings


def build_storage_execution_memory_state(upload_session: dict[str, Any]) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(_provider_descriptor(upload_session))
    provider_descriptor.get("provider_name")
    provider_type = provider_descriptor.get("provider_type")
    if not _is_executable_storage_provider(provider_descriptor):
        return {
            "storage_provider_type": provider_type,
            "object_exists": False,
            "object_handle": None,
        }
    storage_provider = _resolve_concrete_storage_provider(provider_descriptor)
    latest_object = (
        storage_provider.latest_object_for_artifact(upload_session.get("artifact_id"), include_deleted=True)
        if hasattr(storage_provider, "latest_object_for_artifact")
        else None
    )
    object_handle = latest_object.get("object_handle") if isinstance(latest_object, dict) else None
    deleted = bool((latest_object or {}).get("deleted"))
    return {
        "storage_provider_type": storage_provider.descriptor.provider_type,
        "object_exists": bool(latest_object) and not deleted,
        "object_handle": object_handle,
        "object_stored": bool((latest_object or {}).get("uploaded")) and not deleted,
        "file_uploaded": bool((latest_object or {}).get("uploaded")) and not deleted,
        "checksum_calculated": bool((latest_object or {}).get("checksum")) and not deleted,
        "checksum": (latest_object or {}).get("checksum"),
        "content_length": (latest_object or {}).get("size_bytes"),
        "content_type": (latest_object or {}).get("content_type"),
        "deleted": deleted,
        "storage_verified": False,
    }


def _future_execution_request_persistence_descriptor(
    *,
    request_id: str,
    idempotency_key: str | None,
    request_descriptor: dict[str, Any] | None = None,
    descriptor_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "persistence_descriptor_schema_version": "1",
        "persistence_state": "not_persisted",
        "persistence_required": False,
        "persistence_available": False,
        "persistence_status": "not_persisted",
        "future_record_type": "storage_execution_request",
        "future_unique_keys": ["artifact_id", "requested_operation", "idempotency_key"],
        "future_required_columns": [
            "request_id",
            "artifact_id",
            "upload_session_id",
            "execution_session_id",
            "requested_operation",
            "request_status",
            "idempotency_key",
            "provider_name",
            "provider_type",
            "provider_configured",
            "execution_allowed",
            "operation_invoked",
            "object_stored",
            "file_uploaded",
            "checksum_calculated",
            "validation_status",
            "created_from",
            "persistence_status",
        ],
        "future_json_columns": ["request_metadata", "blocking_issues", "warnings"],
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "request_descriptor": dict(request_descriptor or {}),
        "descriptor_validation": dict(descriptor_validation or {}),
        "requires_schema_or_artifact_metadata_persistence": True,
    }


def build_storage_execution_request_descriptor(
    execution_request: dict[str, Any],
) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(
        execution_request.get("provider_descriptor")
        if isinstance(execution_request.get("provider_descriptor"), dict)
        else {}
    )
    validation = execution_request.get("validation") if isinstance(execution_request.get("validation"), dict) else {}
    descriptor = StorageExecutionRequestDescriptor(
        request_id=execution_request.get("request_id"),
        artifact_id=execution_request.get("artifact_id"),
        upload_session_id=execution_request.get("upload_session_id"),
        execution_session_id=execution_request.get("execution_session_id"),
        requested_operation=execution_request.get("requested_operation"),
        requested_by=execution_request.get("requested_by"),
        request_metadata=execution_request.get("request_metadata")
        if isinstance(execution_request.get("request_metadata"), dict)
        else {},
        request_status=execution_request.get("request_status"),
        idempotency_key=(execution_request.get("idempotency") or {}).get("key")
        if isinstance(execution_request.get("idempotency"), dict)
        else None,
        provider_name=provider_descriptor.get("provider_name"),
        provider_type=provider_descriptor.get("provider_type"),
        provider_configured=bool(provider_descriptor.get("configured")),
        execution_allowed=bool(execution_request.get("execution_allowed")),
        operation_invoked=bool(execution_request.get("operation_invoked")),
        object_stored=bool(execution_request.get("object_stored")),
        file_uploaded=bool(execution_request.get("file_uploaded")),
        checksum_calculated=bool(execution_request.get("checksum_calculated")),
        validation_status=validation.get("validation_status"),
        blocking_issues=execution_request.get("blocking_issues")
        if isinstance(execution_request.get("blocking_issues"), list)
        else [],
        warnings=execution_request.get("warnings") if isinstance(execution_request.get("warnings"), list) else [],
        created_from="storage_execution_request_foundation",
        persistence_status="not_persisted",
    )
    return descriptor.as_dict()


def validate_storage_execution_request_descriptor(
    request_descriptor: dict[str, Any],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    concrete_operation_invoked = (
        _is_executable_provider_type(request_descriptor.get("provider_type"))
        and request_descriptor.get("requested_operation")
        in {"create_object", "upload_object", "head_object", "get_object", "delete_object", "verify_object"}
        and bool(request_descriptor.get("operation_invoked"))
    )
    required_fields = (
        "request_id",
        "artifact_id",
        "upload_session_id",
        "execution_session_id",
    )
    for field_name in required_fields:
        if not request_descriptor.get(field_name):
            blocking_issues.append(
                _issue(
                    f"{field_name}_missing",
                    f"Storage execution request descriptor requires {field_name}.",
                    component="storage_execution_request_descriptor",
                )
            )
    if request_descriptor.get("requested_operation") not in STORAGE_EXECUTION_OPERATIONS:
        blocking_issues.append(
            _issue(
                "requested_operation_invalid",
                "Storage execution request descriptor contains an invalid requested_operation.",
                component="storage_execution_request_descriptor",
                item_id=request_descriptor.get("requested_operation"),
            )
        )
    if request_descriptor.get("request_status") not in {
        STORAGE_EXECUTION_REQUEST_STATUS_BLOCKED,
        STORAGE_EXECUTION_REQUEST_STATUS_REQUESTED,
    }:
        blocking_issues.append(
            _issue(
                "request_status_invalid",
                "Storage execution request descriptor contains an invalid request_status.",
                component="storage_execution_request_descriptor",
                item_id=request_descriptor.get("request_status"),
            )
        )
    invariant_false_fields = (
        "execution_allowed",
        "operation_invoked",
    )
    if concrete_operation_invoked:
        invariant_false_fields = ()
    for field_name in invariant_false_fields:
        if bool(request_descriptor.get(field_name)):
            blocking_issues.append(
                _issue(
                    f"{field_name}_must_be_false",
                    f"Storage execution request descriptor requires {field_name}=false.",
                    component="storage_execution_request_descriptor",
                )
            )
    protected_false_fields = (
        () if concrete_operation_invoked else ("object_stored", "file_uploaded", "checksum_calculated")
    )
    for field_name in protected_false_fields:
        if bool(request_descriptor.get(field_name)):
            blocking_issues.append(
                _issue(
                    f"{field_name}_must_be_false",
                    f"Storage execution request descriptor requires {field_name}=false.",
                    component="storage_execution_request_descriptor",
                )
            )
    if request_descriptor.get("persistence_status") != "not_persisted":
        warnings.append(
            _issue(
                "persistence_status_unexpected",
                "Storage execution request descriptor should remain not_persisted in this foundation.",
                component="storage_execution_request_descriptor",
                severity="warning",
            )
        )
    return {
        "descriptor_valid": not blocking_issues,
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def build_storage_execution_verification_descriptor(
    *,
    execution_request: dict[str, Any],
    prepared_execution: dict[str, Any],
) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(
        execution_request.get("provider_descriptor")
        if isinstance(execution_request.get("provider_descriptor"), dict)
        else {}
    )
    prepared_session = (
        prepared_execution.get("storage_execution_session")
        if isinstance(prepared_execution.get("storage_execution_session"), dict)
        else {}
    )
    request_metadata = (
        execution_request.get("request_metadata") if isinstance(execution_request.get("request_metadata"), dict) else {}
    )
    storage_operation_result = (
        execution_request.get("storage_operation_result")
        if isinstance(execution_request.get("storage_operation_result"), dict)
        else {}
    )
    operation_metadata = (
        storage_operation_result.get("metadata") if isinstance(storage_operation_result.get("metadata"), dict) else {}
    )
    verification_result = (
        execution_request.get("storage_verification_result")
        if isinstance(execution_request.get("storage_verification_result"), dict)
        else {}
    )
    descriptor_source = verification_result if verification_result else operation_metadata
    verification_blocking_issues = (
        verification_result.get("blocking_issues")
        if isinstance(verification_result.get("blocking_issues"), list)
        else []
    )
    verification_warnings = (
        verification_result.get("warnings") if isinstance(verification_result.get("warnings"), list) else []
    )
    descriptor = StorageExecutionVerificationDescriptor(
        verification_id=_stable_verification_id(
            request_id=execution_request.get("request_id"),
            artifact_id=execution_request.get("artifact_id"),
            execution_session_id=execution_request.get("execution_session_id"),
        ),
        request_id=execution_request.get("request_id"),
        artifact_id=execution_request.get("artifact_id"),
        upload_session_id=execution_request.get("upload_session_id"),
        execution_session_id=execution_request.get("execution_session_id"),
        requested_operation=execution_request.get("requested_operation"),
        verification_status=verification_result.get("verification_status") or "not_verified",
        verification_required=True,
        verification_available=bool(verification_result.get("verification_available"))
        or bool(operation_metadata.get("object_exists")),
        storage_verified=bool(verification_result.get("storage_verified")),
        object_exists=bool(descriptor_source.get("object_exists")),
        object_stored=bool(descriptor_source.get("object_stored")),
        file_uploaded=bool(descriptor_source.get("file_uploaded")),
        checksum_calculated=bool(descriptor_source.get("checksum_calculated")),
        provider_name=provider_descriptor.get("provider_name"),
        provider_type=provider_descriptor.get("provider_type"),
        provider_configured=bool(provider_descriptor.get("configured")),
        object_handle=(
            descriptor_source.get("object_handle")
            if isinstance(descriptor_source.get("object_handle"), dict)
            else storage_operation_result.get("object_handle")
            if isinstance(storage_operation_result.get("object_handle"), dict)
            else None
        ),
        checksum=descriptor_source.get("checksum"),
        content_length=descriptor_source.get("content_length"),
        content_type=descriptor_source.get("content_type")
        or (request_metadata.get("content_type") if isinstance(request_metadata.get("content_type"), str) else None),
        metadata={
            "created_from": "storage_execution_verification_planning",
            "prepared_execution_state": prepared_session.get("execution_state"),
            "request_status": execution_request.get("request_status"),
            "provider_name": provider_descriptor.get("provider_name"),
            "provider_type": provider_descriptor.get("provider_type"),
            "storage_provider_name": provider_descriptor.get("provider_name"),
            "storage_provider_type": provider_descriptor.get("provider_type"),
            "real_storage_operations_enabled": bool(verification_result)
            and bool(execution_request.get("real_storage_operations_enabled")),
            "provider_operation_invoked": bool(verification_result)
            and bool(execution_request.get("operation_invoked")),
            "verification_runtime": verification_result,
        },
        blocking_issues=[
            *(
                execution_request.get("blocking_issues")
                if isinstance(execution_request.get("blocking_issues"), list)
                else []
            ),
            *verification_blocking_issues,
        ],
        warnings=[
            *(execution_request.get("warnings") if isinstance(execution_request.get("warnings"), list) else []),
            *verification_warnings,
        ],
        persistence_status="not_persisted",
    )
    return descriptor.as_dict()


def validate_storage_execution_verification_descriptor(
    verification_descriptor: dict[str, Any],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    concrete_existing_object_operation_completed = (
        _is_executable_provider_type(verification_descriptor.get("provider_type"))
        and verification_descriptor.get("requested_operation") in {"upload_object", "head_object", "get_object"}
        and bool(verification_descriptor.get("object_exists"))
    )
    concrete_create_completed = (
        _is_executable_provider_type(verification_descriptor.get("provider_type"))
        and verification_descriptor.get("requested_operation") == "create_object"
        and bool(verification_descriptor.get("object_exists"))
    )
    concrete_delete_completed = (
        _is_executable_provider_type(verification_descriptor.get("provider_type"))
        and verification_descriptor.get("requested_operation") == "delete_object"
        and not bool(verification_descriptor.get("object_exists"))
    )
    concrete_verify_completed = (
        _is_executable_provider_type(verification_descriptor.get("provider_type"))
        and verification_descriptor.get("requested_operation") == "verify_object"
        and verification_descriptor.get("verification_status") == "storage_verified"
        and bool(verification_descriptor.get("storage_verified"))
        and bool(verification_descriptor.get("object_exists"))
        and bool(verification_descriptor.get("object_stored"))
        and bool(verification_descriptor.get("file_uploaded"))
        and bool(verification_descriptor.get("checksum_calculated"))
        and bool(verification_descriptor.get("checksum"))
        and isinstance(verification_descriptor.get("content_length"), int)
        and verification_descriptor.get("content_length") >= 0
    )
    for field_name in (
        "verification_id",
        "artifact_id",
        "request_id",
        "execution_session_id",
    ):
        if not verification_descriptor.get(field_name):
            blocking_issues.append(
                _issue(
                    f"{field_name}_missing",
                    f"Storage execution verification descriptor requires {field_name}.",
                    component="storage_execution_verification_descriptor",
                )
            )
    invariant_false_fields = ("storage_verified",)
    if concrete_verify_completed:
        invariant_false_fields = ()
    elif concrete_existing_object_operation_completed:
        invariant_false_fields = ("storage_verified",)
    elif concrete_create_completed:
        invariant_false_fields = (
            "storage_verified",
            "object_stored",
            "checksum_calculated",
        )
    elif concrete_delete_completed:
        invariant_false_fields = (
            "storage_verified",
            "object_exists",
            "object_stored",
            "checksum_calculated",
        )
    else:
        invariant_false_fields = (
            "storage_verified",
            "object_exists",
            "object_stored",
            "checksum_calculated",
        )
    for field_name in invariant_false_fields:
        if bool(verification_descriptor.get(field_name)):
            blocking_issues.append(
                _issue(
                    f"{field_name}_must_be_false",
                    f"Storage execution verification descriptor requires {field_name}=false.",
                    component="storage_execution_verification_descriptor",
                )
            )
    metadata = (
        verification_descriptor.get("metadata") if isinstance(verification_descriptor.get("metadata"), dict) else {}
    )
    if metadata.get("real_storage_operations_enabled") and not concrete_verify_completed:
        blocking_issues.append(
            _issue(
                "real_storage_operations_must_be_disabled",
                "Storage verification planning cannot enable real storage operations.",
                component="storage_execution_verification_descriptor",
            )
        )
    if metadata.get("provider_operation_invoked") and not concrete_verify_completed:
        blocking_issues.append(
            _issue(
                "provider_operation_must_not_be_invoked",
                "Storage verification planning cannot invoke a concrete provider.",
                component="storage_execution_verification_descriptor",
            )
        )
    if verification_descriptor.get("persistence_status") != "not_persisted":
        warnings.append(
            _issue(
                "persistence_status_unexpected",
                "Storage execution verification descriptor should remain not_persisted in this foundation.",
                component="storage_execution_verification_descriptor",
                severity="warning",
            )
        )
    return {
        "descriptor_valid": not blocking_issues,
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def build_storage_execution_result_descriptor(
    *,
    execution_request: dict[str, Any],
    verification_descriptor: dict[str, Any],
    prepared_execution: dict[str, Any],
) -> dict[str, Any]:
    provider_descriptor = _normalize_provider_descriptor(
        execution_request.get("provider_descriptor")
        if isinstance(execution_request.get("provider_descriptor"), dict)
        else {}
    )
    request_metadata = (
        execution_request.get("request_metadata") if isinstance(execution_request.get("request_metadata"), dict) else {}
    )
    storage_operation_result = (
        execution_request.get("storage_operation_result")
        if isinstance(execution_request.get("storage_operation_result"), dict)
        else {}
    )
    operation_metadata = (
        storage_operation_result.get("metadata") if isinstance(storage_operation_result.get("metadata"), dict) else {}
    )
    verification_result = (
        execution_request.get("storage_verification_result")
        if isinstance(execution_request.get("storage_verification_result"), dict)
        else {}
    )
    object_handle = (
        storage_operation_result.get("object_handle")
        if isinstance(storage_operation_result.get("object_handle"), dict)
        else None
    )
    object_created = bool(operation_metadata.get("object_created"))
    object_uploaded = bool(operation_metadata.get("object_stored")) and bool(operation_metadata.get("file_uploaded"))
    verification_succeeded = bool(verification_result.get("storage_verified"))
    verification_failed = bool(verification_result) and not verification_succeeded
    concrete_operation_succeeded = storage_operation_result.get("status") in {
        "object_created",
        "object_uploaded",
        "object_head",
        "object_downloaded",
        "object_deleted",
    }
    operation_invoked = bool(execution_request.get("operation_invoked"))
    real_storage_operations_enabled = bool(execution_request.get("real_storage_operations_enabled"))
    descriptor = StorageExecutionResultDescriptor(
        result_id=_stable_result_id(
            request_id=execution_request.get("request_id"),
            verification_id=verification_descriptor.get("verification_id"),
            artifact_id=execution_request.get("artifact_id"),
            execution_session_id=execution_request.get("execution_session_id"),
        ),
        request_id=execution_request.get("request_id"),
        verification_id=verification_descriptor.get("verification_id"),
        artifact_id=execution_request.get("artifact_id"),
        upload_session_id=execution_request.get("upload_session_id"),
        execution_session_id=execution_request.get("execution_session_id"),
        requested_operation=execution_request.get("requested_operation"),
        result_status=verification_result.get("verification_status")
        or storage_operation_result.get("status")
        or "not_executed",
        execution_started=operation_invoked,
        execution_completed=operation_invoked,
        execution_succeeded=verification_succeeded
        if execution_request.get("requested_operation") == "verify_object"
        else object_created or object_uploaded or concrete_operation_succeeded,
        execution_failed=verification_failed,
        operation_invoked=operation_invoked,
        real_storage_operations_enabled=real_storage_operations_enabled,
        provider_name=provider_descriptor.get("provider_name"),
        provider_type=provider_descriptor.get("provider_type"),
        provider_configured=bool(provider_descriptor.get("configured")),
        object_handle=object_handle,
        object_stored=bool(operation_metadata.get("object_stored")),
        object_exists=bool(operation_metadata.get("object_exists")),
        file_uploaded=bool(operation_metadata.get("file_uploaded")),
        checksum_calculated=bool(operation_metadata.get("checksum_calculated")),
        checksum=operation_metadata.get("checksum"),
        content_length=operation_metadata.get("content_length"),
        content_type=operation_metadata.get("content_type")
        or (request_metadata.get("content_type") if isinstance(request_metadata.get("content_type"), str) else None),
        error_code="storage_verification_failed" if verification_failed else None,
        error_message="Storage verification did not meet all required criteria." if verification_failed else None,
        blocking_issues=execution_request.get("blocking_issues")
        if isinstance(execution_request.get("blocking_issues"), list)
        else [],
        warnings=execution_request.get("warnings") if isinstance(execution_request.get("warnings"), list) else [],
        persistence_status="not_persisted",
    )
    return descriptor.as_dict()


def validate_storage_execution_result_descriptor(
    result_descriptor: dict[str, Any],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    concrete_operation_succeeded = (
        _is_executable_provider_type(result_descriptor.get("provider_type"))
        and result_descriptor.get("requested_operation")
        in {"create_object", "upload_object", "head_object", "get_object", "delete_object", "verify_object"}
        and result_descriptor.get("result_status")
        in {
            "object_created",
            "object_uploaded",
            "object_head",
            "object_downloaded",
            "object_deleted",
            "storage_verified",
        }
    )
    concrete_verification_failed = (
        _is_executable_provider_type(result_descriptor.get("provider_type"))
        and result_descriptor.get("requested_operation") == "verify_object"
        and result_descriptor.get("result_status") == "verification_failed"
    )
    for field_name in (
        "result_id",
        "request_id",
        "verification_id",
        "artifact_id",
        "execution_session_id",
    ):
        if not result_descriptor.get(field_name):
            blocking_issues.append(
                _issue(
                    f"{field_name}_missing",
                    f"Storage execution result descriptor requires {field_name}.",
                    component="storage_execution_result_descriptor",
                )
            )
    invariant_false_fields = (
        "execution_started",
        "execution_completed",
        "execution_succeeded",
        "operation_invoked",
        "real_storage_operations_enabled",
        "object_exists",
    )
    if concrete_operation_succeeded:
        invariant_false_fields = ()
    elif concrete_verification_failed:
        invariant_false_fields = ("execution_succeeded",)
    protected_false_fields = (
        () if concrete_operation_succeeded else ("object_stored", "file_uploaded", "checksum_calculated")
    )
    if concrete_verification_failed:
        protected_false_fields = ()
    for field_name in (*invariant_false_fields, *protected_false_fields):
        if bool(result_descriptor.get(field_name)):
            blocking_issues.append(
                _issue(
                    f"{field_name}_must_be_false",
                    f"Storage execution result descriptor requires {field_name}=false.",
                    component="storage_execution_result_descriptor",
                )
            )
    if result_descriptor.get("persistence_status") != "not_persisted":
        blocking_issues.append(
            _issue(
                "persistence_status_must_be_not_persisted",
                "Storage execution result descriptor must remain not_persisted in this foundation.",
                component="storage_execution_result_descriptor",
            )
        )
    if result_descriptor.get("execution_failed") and not concrete_verification_failed:
        warnings.append(
            _issue(
                "execution_failed_marked_without_execution",
                "Storage execution result descriptor reports execution_failed=true without execution.",
                component="storage_execution_result_descriptor",
                severity="warning",
            )
        )
    return {
        "descriptor_valid": not blocking_issues,
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def build_storage_execution_request(
    upload_session: dict[str, Any],
    *,
    requested_operation: str,
    requested_by: str | None = None,
    request_metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    prepared_execution = build_prepared_storage_execution(upload_session)
    normalized_operation = _normalize_requested_operation(requested_operation)
    operation_entry = _request_operation_entry(
        prepared_execution=prepared_execution,
        requested_operation=normalized_operation,
    )
    action_entry = _request_action_entry(
        prepared_execution=prepared_execution,
        requested_operation=normalized_operation,
    )
    blocking_issues = list(prepared_execution["validation"].get("blocking_issues") or [])
    warnings = list(prepared_execution["validation"].get("warnings") or [])
    if normalized_operation not in STORAGE_EXECUTION_OPERATIONS:
        blocking_issues.append(
            _request_issue(
                code="requested_operation_invalid",
                message="Requested storage operation is not supported by the storage execution request contract.",
                item_id=normalized_operation or str(requested_operation),
            )
        )
    elif operation_entry is None:
        blocking_issues.append(
            _request_issue(
                code="requested_operation_not_planned",
                message="Requested storage operation is not present in the execution plan.",
                item_id=normalized_operation,
            )
        )
    elif operation_entry.get("status") == STORAGE_EXECUTION_STATE_BLOCKED:
        blocking_issues.append(
            _request_issue(
                code="requested_operation_blocked",
                message="Requested storage operation is currently blocked.",
                item_id=normalized_operation,
            )
        )
    if action_entry is None:
        blocking_issues.append(
            _request_issue(
                code="request_action_missing",
                message="Requested storage operation does not have a prepared action model entry.",
                item_id=normalized_operation,
            )
        )
    elif action_entry.get("status") == STORAGE_EXECUTION_STATE_BLOCKED:
        blocking_issues.append(
            _request_issue(
                code="request_action_blocked",
                message="Requested storage operation action is currently blocked.",
                item_id=normalized_operation,
            )
        )
    if action_entry and action_entry.get("execution_allowed"):
        warnings.append(
            _issue(
                "request_action_unexpectedly_executable",
                "Storage execution request action reported execution_allowed=true; request remains non-executing.",
                component="storage_execution_request",
                severity="warning",
                item_id=normalized_operation,
            )
        )
    storage_execution_session = prepared_execution["storage_execution_session"]
    request_id = _stable_request_id(
        artifact_id=storage_execution_session.get("artifact_id"),
        execution_session_id=storage_execution_session.get("execution_session_id"),
        requested_operation=normalized_operation,
        idempotency_key=idempotency_key,
    )
    validation = {
        "validation_status": STORAGE_EXECUTION_REQUEST_STATUS_BLOCKED
        if blocking_issues
        else STORAGE_EXECUTION_REQUEST_STATUS_REQUESTED,
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
        "requested_operation_valid": normalized_operation in STORAGE_EXECUTION_OPERATIONS,
        "requested_operation_planned": operation_entry is not None,
        "requested_operation_blocked": bool(
            operation_entry and operation_entry.get("status") == STORAGE_EXECUTION_STATE_BLOCKED
        ),
        "execution_allowed": False,
        "real_storage_operations_enabled": False,
    }
    request_accepted = validation["validation_status"] == STORAGE_EXECUTION_REQUEST_STATUS_REQUESTED
    memory_verification_result = None
    if normalized_operation == "verify_object":
        memory_runtime_operation, memory_verification_result, memory_blocking_issues, memory_warnings = (
            _execute_memory_verify_object(
                upload_session=upload_session,
                prepared_execution=prepared_execution,
                operation_entry=operation_entry,
                validation=validation,
                request_metadata=request_metadata,
            )
        )
    else:
        memory_runtime_operation, memory_blocking_issues, memory_warnings = _execute_memory_storage_operation(
            upload_session=upload_session,
            prepared_execution=prepared_execution,
            operation_entry=operation_entry,
            validation=validation,
            requested_operation=normalized_operation,
            request_metadata=request_metadata,
        )
    if memory_blocking_issues or memory_warnings:
        validation = {
            **validation,
            "validation_status": STORAGE_EXECUTION_REQUEST_STATUS_BLOCKED
            if memory_blocking_issues
            else validation["validation_status"],
            "blocking_issues": _sort_issues([*validation["blocking_issues"], *memory_blocking_issues]),
            "warnings": _sort_issues([*validation["warnings"], *memory_warnings]),
        }
        request_accepted = validation["validation_status"] == STORAGE_EXECUTION_REQUEST_STATUS_REQUESTED
    storage_operation_result = (
        memory_runtime_operation.get("result")
        if isinstance(memory_runtime_operation, dict) and isinstance(memory_runtime_operation.get("result"), dict)
        else {}
    )
    storage_operation_metadata = (
        storage_operation_result.get("metadata") if isinstance(storage_operation_result.get("metadata"), dict) else {}
    )
    provider_descriptor = prepared_execution["provider_descriptor"]
    execution_request = {
        "storage_execution_request_schema_version": "1",
        "request_id": request_id,
        "artifact_id": storage_execution_session.get("artifact_id"),
        "upload_session_id": storage_execution_session.get("upload_session_id"),
        "execution_session_id": storage_execution_session.get("execution_session_id"),
        "requested_operation": normalized_operation,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "request_status": validation["validation_status"],
        "request_accepted": request_accepted,
        "execution_allowed": bool(memory_runtime_operation),
        "operation_invoked": bool(memory_runtime_operation),
        "real_storage_operations_enabled": bool(memory_runtime_operation),
        "object_stored": bool(storage_operation_metadata.get("object_stored")),
        "file_uploaded": bool(storage_operation_metadata.get("file_uploaded")),
        "checksum_calculated": bool(storage_operation_metadata.get("checksum_calculated")),
        "checksum": storage_operation_metadata.get("checksum"),
        "content_length": storage_operation_metadata.get("content_length"),
        "content_type": storage_operation_metadata.get("content_type"),
        "content_available": bool(storage_operation_metadata.get("content_available")),
        "content_returned": bool(storage_operation_metadata.get("content_returned")),
        "deleted": bool(storage_operation_metadata.get("deleted")),
        "storage_verified": bool((memory_verification_result or {}).get("storage_verified")),
        "storage_verification_status": (memory_verification_result or {}).get("verification_status") or "not_verified",
        "storage_verification_available": bool((memory_verification_result or {}).get("verification_available")),
        "object_exists": bool(storage_operation_metadata.get("object_exists")),
        "object_handle": storage_operation_result.get("object_handle"),
        "storage_operation_result": storage_operation_result,
        "storage_runtime_operation": memory_runtime_operation,
        "storage_verification_result": memory_verification_result,
        "requested_by": requested_by.strip() if isinstance(requested_by, str) and requested_by.strip() else None,
        "request_metadata": dict(request_metadata or {}),
        "provider_descriptor": provider_descriptor,
        "validation": validation,
        "blocking_issues": validation["blocking_issues"],
        "warnings": validation["warnings"],
        "next_available_actions": prepared_execution["next_available_actions"],
        "idempotency": {
            "key": idempotency_key,
            "status": "not_persisted",
            "replay_supported": False,
            "duplicate_persistence_prevented": False,
        },
        "prepared_execution": prepared_execution["prepared_execution"],
        "storage_execution_session": storage_execution_session,
        "execution_plan": prepared_execution["execution_plan"],
        "action_model": prepared_execution["action_model"],
        "runtime_trace": prepared_execution["runtime_trace"],
        "persistence_required": False,
        "persistence_available": False,
        "persistence_status": "not_persisted",
    }
    request_descriptor = build_storage_execution_request_descriptor(execution_request)
    descriptor_validation = validate_storage_execution_request_descriptor(request_descriptor)
    future_persistence_descriptor = _future_execution_request_persistence_descriptor(
        request_id=request_id,
        idempotency_key=idempotency_key,
        request_descriptor=request_descriptor,
        descriptor_validation=descriptor_validation,
    )
    verification_descriptor = build_storage_execution_verification_descriptor(
        execution_request=execution_request,
        prepared_execution=prepared_execution,
    )
    verification_validation = validate_storage_execution_verification_descriptor(verification_descriptor)
    result_descriptor = build_storage_execution_result_descriptor(
        execution_request=execution_request,
        verification_descriptor=verification_descriptor,
        prepared_execution=prepared_execution,
    )
    result_validation = validate_storage_execution_result_descriptor(result_descriptor)
    verification_available = bool(verification_descriptor.get("verification_available"))
    storage_verified = bool(verification_descriptor.get("storage_verified"))
    object_verification_status = verification_descriptor.get("verification_status") or "not_verified"
    result_available = bool(result_descriptor.get("operation_invoked"))
    execution_request = {
        **execution_request,
        "request_descriptor": request_descriptor,
        "descriptor_validation": descriptor_validation,
        "future_persistence_descriptor": future_persistence_descriptor,
        "verification_descriptor": verification_descriptor,
        "verification_validation": verification_validation,
        "verification_required": True,
        "verification_available": verification_available,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "storage_verified": storage_verified,
        "object_exists": bool(result_descriptor.get("object_exists")),
        "object_verification_status": object_verification_status,
        "storage_verification_status": object_verification_status,
        "storage_verification_available": verification_available,
        "processing_handoff_prerequisite_met": storage_verified,
        "verification_persistence_status": "not_persisted",
        "result_descriptor": result_descriptor,
        "result_validation": result_validation,
        "result_required": True,
        "result_available": result_available,
        "storage_execution_result_status": result_descriptor.get("result_status") or "not_executed",
        "result_persistence_status": "not_persisted",
    }
    return {
        "execution_request": execution_request,
        "prepared_execution": prepared_execution,
        "validation": validation,
        "request_descriptor": request_descriptor,
        "descriptor_validation": descriptor_validation,
        "future_persistence_descriptor": future_persistence_descriptor,
        "verification_descriptor": verification_descriptor,
        "verification_validation": verification_validation,
        "verification_required": True,
        "verification_available": verification_available,
        "provider_name": provider_descriptor.get("provider_name"),
        "provider_type": provider_descriptor.get("provider_type"),
        "storage_provider_name": provider_descriptor.get("provider_name"),
        "storage_provider_type": provider_descriptor.get("provider_type"),
        "storage_verified": storage_verified,
        "object_exists": bool(result_descriptor.get("object_exists")),
        "object_verification_status": object_verification_status,
        "storage_verification_status": object_verification_status,
        "storage_verification_available": verification_available,
        "processing_handoff_prerequisite_met": storage_verified,
        "verification_persistence_status": "not_persisted",
        "result_descriptor": result_descriptor,
        "result_validation": result_validation,
        "result_required": True,
        "result_available": result_available,
        "storage_execution_result_status": result_descriptor.get("result_status") or "not_executed",
        "result_persistence_status": "not_persisted",
        "persistence_required": False,
        "persistence_available": False,
        "persistence_status": "not_persisted",
        "blocking_issues": validation["blocking_issues"],
        "warnings": validation["warnings"],
        "next_available_actions": prepared_execution["next_available_actions"],
    }
