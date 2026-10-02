"""Runtime adapter for provider-neutral storage operation preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
    STORAGE_PROVIDER_TYPE_CONFIGURABLE,
    StorageObjectHandle,
    StorageOperationRequest,
    StorageOperationResult,
    StorageProvider,
    build_create_storage_request,
    build_delete_storage_request,
    build_download_storage_request,
    build_head_storage_request,
    build_storage_not_configured_result,
    build_storage_operation_request,
    build_upload_storage_request,
    normalize_storage_operation,
)

STORAGE_OPERATION_STATE_REQUESTED = "requested"
STORAGE_OPERATION_STATE_PLANNED = "planned"
STORAGE_OPERATION_STATE_BLOCKED = "blocked"
STORAGE_OPERATION_STATE_SKIPPED = "skipped"
STORAGE_OPERATION_STATE_NOT_CONFIGURED = "not_configured"
STORAGE_OPERATION_STATE_FUTURE_READY = "future_ready"

REQUIRED_STORAGE_CONFIGURATION_STEP = "configure_storage_provider"

STORAGE_OPERATION_STAGES = {
    STORAGE_OPERATION_CREATE: "binary_upload_object_registration",
    STORAGE_OPERATION_UPLOAD: "binary_upload_content_transfer",
    STORAGE_OPERATION_HEAD: "binary_upload_verification",
    STORAGE_OPERATION_DOWNLOAD: "binary_upload_download",
    STORAGE_OPERATION_DELETE: "binary_upload_compensation",
    STORAGE_OPERATION_GET: "binary_upload_object_read",
    STORAGE_OPERATION_GENERATE_DOWNLOAD: "binary_upload_download_link",
    STORAGE_OPERATION_GENERATE_UPLOAD: "binary_upload_execution",
}


@dataclass(frozen=True)
class StorageRuntimeOperation:
    operation: str
    state: str
    request: StorageOperationRequest
    result: StorageOperationResult
    execution_allowed: bool = False
    invoked: bool = False
    missing_configuration_reason: str | None = None
    required_next_step: str | None = REQUIRED_STORAGE_CONFIGURATION_STEP

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "state": self.state,
            "execution_allowed": self.execution_allowed,
            "invoked": self.invoked,
            "missing_configuration_reason": self.missing_configuration_reason,
            "required_next_step": self.required_next_step,
            "request": self.request.as_dict(),
            "result": self.result.as_dict(),
        }


class StorageProviderRuntimeAdapter:
    """Prepare provider operations and keep runtime execution provider-neutral."""

    def __init__(self) -> None:
        self._request_builders: dict[str, Callable[..., StorageOperationRequest]] = {
            STORAGE_OPERATION_CREATE: build_create_storage_request,
            STORAGE_OPERATION_UPLOAD: build_upload_storage_request,
            STORAGE_OPERATION_HEAD: build_head_storage_request,
            STORAGE_OPERATION_DOWNLOAD: build_download_storage_request,
            STORAGE_OPERATION_DELETE: build_delete_storage_request,
            STORAGE_OPERATION_GET: lambda **kwargs: build_storage_operation_request(
                operation=STORAGE_OPERATION_GET,
                **kwargs,
            ),
            STORAGE_OPERATION_GENERATE_UPLOAD: lambda **kwargs: build_storage_operation_request(
                operation=STORAGE_OPERATION_GENERATE_UPLOAD,
                **kwargs,
            ),
            STORAGE_OPERATION_GENERATE_DOWNLOAD: lambda **kwargs: build_storage_operation_request(
                operation=STORAGE_OPERATION_GENERATE_DOWNLOAD,
                **kwargs,
            ),
        }
        self._provider_methods: dict[str, str] = {
            STORAGE_OPERATION_CREATE: "create_object",
            STORAGE_OPERATION_UPLOAD: "upload_object",
            STORAGE_OPERATION_HEAD: "head_object",
            STORAGE_OPERATION_DOWNLOAD: "get_object",
            STORAGE_OPERATION_GET: "get_object",
            STORAGE_OPERATION_DELETE: "delete_object",
            STORAGE_OPERATION_GENERATE_UPLOAD: "generate_upload",
            STORAGE_OPERATION_GENERATE_DOWNLOAD: "generate_download",
        }

    def prepare_request(
        self,
        *,
        storage_provider: StorageProvider,
        operation: str,
        storage_descriptor: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> StorageOperationRequest:
        normalized_operation = normalize_storage_operation(operation)
        builder = self._request_builders[normalized_operation]
        operation_metadata = {
            "stage": STORAGE_OPERATION_STAGES.get(normalized_operation, normalized_operation),
            **dict(metadata or {}),
        }
        object_handle_value = storage_descriptor.get("object_handle")
        if isinstance(object_handle_value, dict):
            object_handle = StorageObjectHandle(
                provider_name=storage_provider.provider_name,
                provider_type=storage_provider.provider_type,
                reference=dict(object_handle_value.get("reference") or object_handle_value),
            )
        elif isinstance(object_handle_value, str) and object_handle_value.strip():
            object_handle = StorageObjectHandle(
                provider_name=storage_provider.provider_name,
                provider_type=storage_provider.provider_type,
                reference={"object_handle": object_handle_value.strip()},
            )
        else:
            object_handle = None
        payload_value = storage_descriptor.get("content")
        if isinstance(payload_value, bytes):
            payload = payload_value
        elif isinstance(payload_value, str):
            payload = payload_value.encode("utf-8")
        else:
            payload = None
        return builder(
            provider=storage_provider.descriptor,
            descriptor=storage_descriptor,
            metadata=operation_metadata,
            object_handle=object_handle,
            requested_by=storage_descriptor.get("requested_by"),
            payload=payload,
        )

    def prepare_operations(
        self,
        *,
        storage_provider: StorageProvider,
        storage_descriptor: dict[str, Any],
    ) -> dict[str, StorageOperationRequest]:
        return {
            operation: self.prepare_request(
                storage_provider=storage_provider,
                operation=operation,
                storage_descriptor=storage_descriptor,
            )
            for operation in self._request_builders
        }

    def build_operation(
        self,
        *,
        storage_provider: StorageProvider,
        operation: str,
        storage_descriptor: dict[str, Any],
        execute: bool = False,
    ) -> StorageRuntimeOperation:
        normalized_operation = normalize_storage_operation(operation)
        request = self.prepare_request(
            storage_provider=storage_provider,
            operation=normalized_operation,
            storage_descriptor=storage_descriptor,
        )
        readiness = self._operation_readiness(
            storage_provider=storage_provider,
            operation=normalized_operation,
        )
        if execute and readiness["execution_allowed"]:
            provider_method_name = self._provider_methods[normalized_operation]
            result = getattr(storage_provider, provider_method_name)(request)
            return StorageRuntimeOperation(
                operation=normalized_operation,
                state=STORAGE_OPERATION_STATE_FUTURE_READY if result.storage_ready else STORAGE_OPERATION_STATE_BLOCKED,
                request=request,
                result=result,
                execution_allowed=True,
                invoked=True,
                missing_configuration_reason=None if result.storage_ready else result.status,
                required_next_step=result.required_next_step,
            )

        if readiness["execution_allowed"]:
            result = StorageOperationResult(
                operation=normalized_operation,
                status=STORAGE_OPERATION_STATE_FUTURE_READY,
                provider=storage_provider.descriptor,
                executed=False,
                storage_ready=True,
                object_handle=None,
                metadata={
                    "requested_by": request.requested_by,
                    "descriptor": dict(request.descriptor),
                    "operation_request": request.as_dict(),
                    "execution_mode": "prepared_only",
                    "dry_run_prepared": True,
                    "real_storage_operations_enabled": False,
                },
                required_next_step=None,
            )
            return StorageRuntimeOperation(
                operation=normalized_operation,
                state=STORAGE_OPERATION_STATE_FUTURE_READY,
                request=request,
                result=result,
                execution_allowed=True,
                invoked=False,
                missing_configuration_reason=None,
                required_next_step=None,
            )

        result = self._blocked_operation_result(
            request=request,
            storage_provider=storage_provider,
            readiness=readiness,
        )
        return StorageRuntimeOperation(
            operation=normalized_operation,
            state=readiness["state"],
            request=request,
            result=result,
            execution_allowed=readiness["execution_allowed"],
            invoked=False,
            missing_configuration_reason=readiness["missing_configuration_reason"],
            required_next_step=readiness["required_next_step"],
        )

    def build_runtime_trace(
        self,
        *,
        storage_provider: StorageProvider,
        storage_descriptor: dict[str, Any],
        requested_operation: str = STORAGE_OPERATION_GENERATE_UPLOAD,
        execute: bool = False,
    ) -> dict[str, Any]:
        normalized_operation = normalize_storage_operation(requested_operation)
        prepared_operations = self.prepare_operations(
            storage_provider=storage_provider,
            storage_descriptor=storage_descriptor,
        )
        runtime_operation = self.build_operation(
            storage_provider=storage_provider,
            operation=normalized_operation,
            storage_descriptor=storage_descriptor,
            execute=execute,
        )
        provider_descriptor = storage_provider.descriptor
        return {
            "storage_runtime_trace_schema_version": "1",
            "requested_operation": normalized_operation,
            "runtime_state": runtime_operation.state,
            "execution_prepared": True,
            "execution_allowed": runtime_operation.execution_allowed,
            "operation_invoked": runtime_operation.invoked,
            "provider_name": provider_descriptor.provider_name,
            "provider_type": provider_descriptor.provider_type,
            "provider_configured": provider_descriptor.configured,
            "provider_status": provider_descriptor.status,
            "provider_descriptor": provider_descriptor.as_dict(),
            "capabilities": [capability.as_dict() for capability in provider_descriptor.capabilities],
            "missing_configuration_reason": runtime_operation.missing_configuration_reason,
            "required_next_step": runtime_operation.required_next_step,
            "dry_run_prepared": bool(runtime_operation.result.metadata.get("dry_run_prepared")),
            "real_storage_operations_enabled": False,
            "operation_request": runtime_operation.request.as_dict(),
            "operation_result": runtime_operation.result.as_dict(),
            "operations": {operation: request.as_dict() for operation, request in prepared_operations.items()},
            "state_model": {
                "requested": STORAGE_OPERATION_STATE_REQUESTED,
                "planned": STORAGE_OPERATION_STATE_PLANNED,
                "blocked": STORAGE_OPERATION_STATE_BLOCKED,
                "skipped": STORAGE_OPERATION_STATE_SKIPPED,
                "not_configured": STORAGE_OPERATION_STATE_NOT_CONFIGURED,
                "future_ready": STORAGE_OPERATION_STATE_FUTURE_READY,
            },
        }

    def _operation_readiness(
        self,
        *,
        storage_provider: StorageProvider,
        operation: str,
    ) -> dict[str, Any]:
        provider_descriptor = storage_provider.descriptor
        capability = provider_descriptor.capability(operation)
        provider_is_null = provider_descriptor.provider_type == "null" or provider_descriptor.provider_name == "null"
        if provider_is_null:
            return {
                "state": STORAGE_OPERATION_STATE_NOT_CONFIGURED,
                "execution_allowed": False,
                "missing_configuration_reason": STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
                "required_next_step": REQUIRED_STORAGE_CONFIGURATION_STEP,
            }
        if not provider_descriptor.configured:
            return {
                "state": STORAGE_OPERATION_STATE_NOT_CONFIGURED,
                "execution_allowed": False,
                "missing_configuration_reason": provider_descriptor.missing_configuration_reason
                or provider_descriptor.status,
                "required_next_step": "complete_storage_provider_configuration"
                if provider_descriptor.provider_type == STORAGE_PROVIDER_TYPE_CONFIGURABLE
                else REQUIRED_STORAGE_CONFIGURATION_STEP,
            }
        if not capability.supported:
            return {
                "state": STORAGE_OPERATION_STATE_BLOCKED,
                "execution_allowed": False,
                "missing_configuration_reason": "provider_capability_not_supported",
                "required_next_step": f"enable_{operation}_capability",
            }
        if not capability.configured:
            return {
                "state": STORAGE_OPERATION_STATE_BLOCKED,
                "execution_allowed": False,
                "missing_configuration_reason": capability.status,
                "required_next_step": f"configure_{operation}_capability",
            }
        return {
            "state": STORAGE_OPERATION_STATE_FUTURE_READY,
            "execution_allowed": True,
            "missing_configuration_reason": None,
            "required_next_step": None,
        }

    def _blocked_operation_result(
        self,
        *,
        request: StorageOperationRequest,
        storage_provider: StorageProvider,
        readiness: dict[str, Any],
    ) -> StorageOperationResult:
        base_result = build_storage_not_configured_result(request)
        provider_descriptor = storage_provider.descriptor
        return StorageOperationResult(
            operation=base_result.operation,
            status=provider_descriptor.status
            if provider_descriptor.provider_type == STORAGE_PROVIDER_TYPE_CONFIGURABLE
            else base_result.status,
            provider=provider_descriptor,
            executed=False,
            storage_ready=False,
            object_handle=None,
            metadata={
                **base_result.metadata,
                "dry_run_prepared": True,
                "storage_execution_blocked": True,
                "real_storage_operations_enabled": False,
                "missing_configuration_reason": readiness["missing_configuration_reason"],
                "required_configuration_keys": list(provider_descriptor.required_configuration_keys),
            },
            required_next_step=readiness["required_next_step"],
        )


default_storage_provider_runtime_adapter = StorageProviderRuntimeAdapter()


def get_storage_provider_runtime_adapter() -> StorageProviderRuntimeAdapter:
    return default_storage_provider_runtime_adapter
