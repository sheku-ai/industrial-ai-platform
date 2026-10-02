"""Provider-neutral storage contract definitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

STORAGE_PROVIDER_STATUS_NOT_CONFIGURED = "storage_not_configured"
STORAGE_PROVIDER_STATUS_CONFIGURED = "configured"
STORAGE_PROVIDER_STATUS_CONFIGURATION_INCOMPLETE = "configuration_incomplete"
STORAGE_PROVIDER_TYPE_NULL = "null"
STORAGE_PROVIDER_TYPE_CONFIGURABLE = "configurable"

STORAGE_OPERATION_NONE = "none"
STORAGE_OPERATION_CREATE = "create"
STORAGE_OPERATION_UPLOAD = "upload"
STORAGE_OPERATION_HEAD = "head"
STORAGE_OPERATION_DOWNLOAD = "download"
STORAGE_OPERATION_DELETE = "delete"
STORAGE_OPERATION_GET = "get"
STORAGE_OPERATION_GENERATE_UPLOAD = "generate_upload"
STORAGE_OPERATION_GENERATE_DOWNLOAD = "generate_download"


@dataclass(frozen=True)
class StorageProviderCapability:
    operation: str
    supported: bool
    configured: bool = False
    status: str = STORAGE_PROVIDER_STATUS_NOT_CONFIGURED
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "supported": self.supported,
            "configured": self.configured,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StorageProviderDescriptor:
    provider_name: str
    provider_type: str
    configured: bool
    status: str
    capabilities: tuple[StorageProviderCapability, ...] = field(default_factory=tuple)
    missing_configuration_reason: str | None = None
    required_configuration_keys: tuple[str, ...] = field(default_factory=tuple)
    safe_configuration_fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def capability(self, operation: str) -> StorageProviderCapability:
        normalized_operation = normalize_storage_operation(operation)
        for capability in self.capabilities:
            if capability.operation == normalized_operation:
                return capability
        return StorageProviderCapability(
            operation=normalized_operation,
            supported=False,
            configured=self.configured,
            status=self.status,
            reason="operation_not_declared",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "configured": self.configured,
            "status": self.status,
            "capabilities": [capability.as_dict() for capability in self.capabilities],
            "missing_configuration_reason": self.missing_configuration_reason,
            "required_configuration_keys": list(self.required_configuration_keys),
            "safe_configuration_fingerprint": self.safe_configuration_fingerprint,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StorageObjectHandle:
    provider_name: str | None = None
    provider_type: str | None = None
    reference: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "reference": dict(self.reference),
        }


@dataclass(frozen=True)
class StorageOperationRequest:
    operation: str
    provider: StorageProviderDescriptor
    object_handle: StorageObjectHandle | None = None
    descriptor: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    requested_by: str | None = None
    payload: bytes | None = None

    def as_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        result = {
            "operation": self.operation,
            "provider": self.provider.as_dict(),
            "object_handle": self.object_handle.as_dict() if self.object_handle else None,
            "descriptor": dict(self.descriptor),
            "metadata": dict(self.metadata),
            "requested_by": self.requested_by,
            "payload_included": self.payload is not None,
        }
        if include_payload:
            result["payload"] = self.payload
        return result


@dataclass(frozen=True)
class StorageOperationResult:
    operation: str
    status: str
    provider: StorageProviderDescriptor
    executed: bool = False
    storage_ready: bool = False
    object_handle: StorageObjectHandle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    required_next_step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "provider": self.provider.as_dict(),
            "executed": self.executed,
            "storage_ready": self.storage_ready,
            "object_handle": self.object_handle.as_dict() if self.object_handle else None,
            "metadata": dict(self.metadata),
            "required_next_step": self.required_next_step,
        }


@dataclass(frozen=True)
class StorageProviderRequest:
    object_handle: StorageObjectHandle | None = None
    descriptor: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    requested_by: str | None = None


@dataclass(frozen=True)
class StorageProviderUploadRequest(StorageProviderRequest):
    payload: bytes | None = None


@dataclass(frozen=True)
class StorageProviderOperationResult:
    operation: str
    status: str
    provider_name: str
    provider_type: str
    provider_configured: bool
    executed: bool = False
    object_handle: StorageObjectHandle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_operation_result(cls, result: StorageOperationResult) -> StorageProviderOperationResult:
        return cls(
            operation=result.operation,
            status=result.status,
            provider_name=result.provider.provider_name,
            provider_type=result.provider.provider_type,
            provider_configured=result.provider.configured,
            executed=result.executed,
            object_handle=result.object_handle,
            metadata=result.metadata,
        )


class StorageProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def provider_type(self) -> str: ...

    @property
    def configured(self) -> bool: ...

    @property
    def descriptor(self) -> StorageProviderDescriptor: ...

    def create_object(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def upload_object(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def delete_object(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def get_object(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def head_object(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def generate_download(self, request: StorageOperationRequest) -> StorageOperationResult: ...

    def generate_upload(self, request: StorageOperationRequest) -> StorageOperationResult: ...


def normalize_storage_operation(operation: str) -> str:
    normalized = operation.strip().lower().replace("-", "_")
    aliases = {
        "create_object": STORAGE_OPERATION_CREATE,
        "upload_object": STORAGE_OPERATION_UPLOAD,
        "head_object": STORAGE_OPERATION_HEAD,
        "get_object": STORAGE_OPERATION_GET,
        "read_object": STORAGE_OPERATION_GET,
        "download_object": STORAGE_OPERATION_DOWNLOAD,
        "delete_object": STORAGE_OPERATION_DELETE,
        "generate_upload": STORAGE_OPERATION_GENERATE_UPLOAD,
        "generate_upload_object": STORAGE_OPERATION_GENERATE_UPLOAD,
        "generate_download": STORAGE_OPERATION_GENERATE_DOWNLOAD,
        "generate_download_object": STORAGE_OPERATION_GENERATE_DOWNLOAD,
        "download": STORAGE_OPERATION_DOWNLOAD,
    }
    return aliases.get(normalized, normalized)


def normalize_storage_provider_name(provider_name: str | None) -> str:
    if not isinstance(provider_name, str):
        return STORAGE_PROVIDER_TYPE_NULL
    normalized = provider_name.strip().lower()
    return normalized or STORAGE_PROVIDER_TYPE_NULL


def _stable_storage_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower()
    secret_markers = (
        "secret",
        "password",
        "passwd",
        "token",
        "credential",
        "private",
        "access_key",
        "api_key",
        "connection_string",
        "sas",
    )
    return any(marker in normalized for marker in secret_markers)


def sanitize_storage_provider_configuration(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = sanitize_storage_provider_configuration(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_storage_provider_configuration(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_storage_provider_configuration(item) for item in value]
    return value


def safe_storage_configuration_fingerprint(configuration: dict[str, Any]) -> str | None:
    if not configuration:
        return None
    sanitized = sanitize_storage_provider_configuration(configuration)
    digest = hashlib.sha256(_stable_storage_json(sanitized).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_storage_provider_capability(
    *,
    operation: str,
    supported: bool,
    configured: bool = False,
    status: str | None = None,
    reason: str | None = None,
) -> StorageProviderCapability:
    return StorageProviderCapability(
        operation=normalize_storage_operation(operation),
        supported=bool(supported),
        configured=bool(configured),
        status=status or STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
        reason=reason,
    )


def build_storage_provider_descriptor(
    *,
    provider_name: str | None,
    provider_type: str | None,
    configured: bool,
    status: str | None,
    capabilities: tuple[StorageProviderCapability, ...] | list[StorageProviderCapability] | None = None,
    missing_configuration_reason: str | None = None,
    required_configuration_keys: tuple[str, ...] | list[str] | None = None,
    safe_configuration_fingerprint: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> StorageProviderDescriptor:
    return StorageProviderDescriptor(
        provider_name=normalize_storage_provider_name(provider_name),
        provider_type=normalize_storage_provider_name(provider_type),
        configured=bool(configured),
        status=status or STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
        capabilities=tuple(capabilities or ()),
        missing_configuration_reason=missing_configuration_reason,
        required_configuration_keys=tuple(required_configuration_keys or ()),
        safe_configuration_fingerprint=safe_configuration_fingerprint,
        metadata=dict(metadata or {}),
    )


def build_null_capabilities() -> tuple[StorageProviderCapability, ...]:
    return tuple(
        build_storage_provider_capability(
            operation=operation,
            supported=False,
            configured=False,
            status=STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
            reason="storage_provider_not_configured",
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


def build_null_storage_provider_descriptor() -> StorageProviderDescriptor:
    return build_storage_provider_descriptor(
        provider_name=STORAGE_PROVIDER_TYPE_NULL,
        provider_type=STORAGE_PROVIDER_TYPE_NULL,
        configured=False,
        status=STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
        capabilities=build_null_capabilities(),
    )


CONFIGURABLE_STORAGE_REQUIRED_KEYS = (
    "provider_name",
    "provider_type",
    "capabilities",
)


def _configured_capability_operations(configuration: dict[str, Any]) -> set[str]:
    raw_capabilities = configuration.get("capabilities")
    raw_operations = configuration.get("operations", configuration.get("supported_operations"))
    operations: set[str] = set()
    if isinstance(raw_capabilities, dict):
        values = raw_capabilities.get("operations", raw_capabilities.get("supported_operations"))
        if isinstance(values, list | tuple | set):
            operations.update(normalize_storage_operation(str(item)) for item in values if str(item).strip())
        for key, value in raw_capabilities.items():
            if key not in {"operations", "supported_operations"} and value:
                operations.add(normalize_storage_operation(str(key)))
    elif isinstance(raw_capabilities, list | tuple | set):
        for item in raw_capabilities:
            if isinstance(item, str) and item.strip():
                operations.add(normalize_storage_operation(item))
            elif isinstance(item, dict):
                operation = item.get("operation") or item.get("name")
                if isinstance(operation, str) and item.get("supported", True):
                    operations.add(normalize_storage_operation(operation))
    if isinstance(raw_operations, list | tuple | set):
        operations.update(normalize_storage_operation(str(item)) for item in raw_operations if str(item).strip())
    return operations


def _build_configurable_capabilities(
    *,
    configuration: dict[str, Any],
    configured: bool,
    status: str,
) -> tuple[StorageProviderCapability, ...]:
    configured_operations = _configured_capability_operations(configuration)
    return tuple(
        build_storage_provider_capability(
            operation=operation,
            supported=operation in configured_operations,
            configured=configured and operation in configured_operations,
            status=STORAGE_PROVIDER_STATUS_CONFIGURED if configured and operation in configured_operations else status,
            reason=None if configured and operation in configured_operations else "operation_not_configured",
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


def _configurable_storage_readiness(configuration: dict[str, Any]) -> dict[str, Any]:
    missing_keys = [key for key in CONFIGURABLE_STORAGE_REQUIRED_KEYS if not configuration.get(key)]
    configured_operations = _configured_capability_operations(configuration)
    if STORAGE_OPERATION_GENERATE_UPLOAD not in configured_operations:
        missing_keys.append("capabilities.generate_upload")
    configured = not missing_keys
    reason = None if configured else "missing_required_configuration"
    return {
        "configured": configured,
        "status": STORAGE_PROVIDER_STATUS_CONFIGURED
        if configured
        else STORAGE_PROVIDER_STATUS_CONFIGURATION_INCOMPLETE,
        "missing_configuration_reason": reason,
        "missing_configuration_keys": missing_keys,
    }


def build_configurable_storage_provider_descriptor(
    configuration: dict[str, Any] | None = None,
) -> StorageProviderDescriptor:
    normalized_configuration = dict(configuration or {})
    if normalized_configuration.get("provider_name") is None and normalized_configuration.get("name") is not None:
        normalized_configuration["provider_name"] = normalized_configuration["name"]
    if normalized_configuration.get("provider_type") is None and normalized_configuration.get("type") is not None:
        normalized_configuration["provider_type"] = normalized_configuration["type"]
    if normalized_configuration.get("capabilities") is None:
        configured_operations = normalized_configuration.get(
            "operations", normalized_configuration.get("supported_operations")
        )
        if configured_operations is not None:
            normalized_configuration["capabilities"] = {"operations": configured_operations}
    readiness = _configurable_storage_readiness(normalized_configuration)
    provider_name = (
        normalized_configuration.get("provider_name")
        or normalized_configuration.get("name")
        or STORAGE_PROVIDER_TYPE_CONFIGURABLE
    )
    provider_type = (
        normalized_configuration.get("provider_type")
        or normalized_configuration.get("type")
        or STORAGE_PROVIDER_TYPE_CONFIGURABLE
    )
    configured = bool(readiness["configured"])
    status = str(readiness["status"])
    missing_keys = tuple(str(item) for item in readiness["missing_configuration_keys"])
    sanitized_configuration = sanitize_storage_provider_configuration(normalized_configuration)
    return build_storage_provider_descriptor(
        provider_name=str(provider_name),
        provider_type=str(provider_type),
        configured=configured,
        status=status,
        capabilities=_build_configurable_capabilities(
            configuration=normalized_configuration,
            configured=configured,
            status=status,
        ),
        missing_configuration_reason=readiness["missing_configuration_reason"],
        required_configuration_keys=missing_keys,
        safe_configuration_fingerprint=safe_storage_configuration_fingerprint(normalized_configuration),
        metadata={
            "configuration_source": "runtime_selection",
            "safe_configuration": sanitized_configuration,
            "secrets_redacted": sanitized_configuration != normalized_configuration,
            "real_storage_operations_enabled": False,
        },
    )


def build_storage_operation_request(
    *,
    operation: str,
    provider: StorageProviderDescriptor,
    descriptor: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    object_handle: StorageObjectHandle | None = None,
    requested_by: str | None = None,
    payload: bytes | None = None,
) -> StorageOperationRequest:
    return StorageOperationRequest(
        operation=normalize_storage_operation(operation),
        provider=provider,
        object_handle=object_handle,
        descriptor=dict(descriptor or {}),
        metadata=dict(metadata or {}),
        requested_by=requested_by.strip() if isinstance(requested_by, str) and requested_by.strip() else None,
        payload=payload,
    )


def build_create_storage_request(**kwargs: Any) -> StorageOperationRequest:
    return build_storage_operation_request(operation=STORAGE_OPERATION_CREATE, **kwargs)


def build_upload_storage_request(**kwargs: Any) -> StorageOperationRequest:
    return build_storage_operation_request(operation=STORAGE_OPERATION_UPLOAD, **kwargs)


def build_head_storage_request(**kwargs: Any) -> StorageOperationRequest:
    return build_storage_operation_request(operation=STORAGE_OPERATION_HEAD, **kwargs)


def build_download_storage_request(**kwargs: Any) -> StorageOperationRequest:
    return build_storage_operation_request(operation=STORAGE_OPERATION_DOWNLOAD, **kwargs)


def build_delete_storage_request(**kwargs: Any) -> StorageOperationRequest:
    return build_storage_operation_request(operation=STORAGE_OPERATION_DELETE, **kwargs)


def build_storage_not_configured_result(request: StorageOperationRequest) -> StorageOperationResult:
    return StorageOperationResult(
        operation=request.operation,
        status=STORAGE_PROVIDER_STATUS_NOT_CONFIGURED,
        provider=request.provider,
        executed=False,
        storage_ready=False,
        object_handle=None,
        metadata={
            "requested_by": request.requested_by,
            "descriptor": dict(request.descriptor),
            "operation_request": request.as_dict(),
        },
        required_next_step="configure_storage_provider",
    )


class NullStorageProvider:
    provider_name = "null"
    provider_type = "null"
    configured = False

    def __init__(self) -> None:
        self._descriptor = build_null_storage_provider_descriptor()

    @property
    def descriptor(self) -> StorageProviderDescriptor:
        return self._descriptor

    def _result(self, operation: str, request: StorageOperationRequest | None = None) -> StorageOperationResult:
        operation_request = request or build_storage_operation_request(
            operation=operation,
            provider=self.descriptor,
        )
        return build_storage_not_configured_result(operation_request)

    def create_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("create_object", request)

    def upload_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("upload_object", request)

    def delete_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("delete_object", request)

    def get_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("get_object", request)

    def head_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("head_object", request)

    def generate_download(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("generate_download", request)

    def generate_upload(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result("generate_upload", request)


class ConfigurableStorageProvider:
    provider_name = STORAGE_PROVIDER_TYPE_CONFIGURABLE
    provider_type = STORAGE_PROVIDER_TYPE_CONFIGURABLE

    def __init__(self, configuration: dict[str, Any] | None = None) -> None:
        self._configuration = dict(configuration or {})
        self._descriptor = build_configurable_storage_provider_descriptor(self._configuration)
        self.provider_name = self._descriptor.provider_name
        self.provider_type = self._descriptor.provider_type

    @property
    def configured(self) -> bool:
        return self._descriptor.configured

    @property
    def descriptor(self) -> StorageProviderDescriptor:
        return self._descriptor

    def _result(self, request: StorageOperationRequest) -> StorageOperationResult:
        if not self.configured:
            result = build_storage_not_configured_result(request)
            return StorageOperationResult(
                operation=result.operation,
                status=self.descriptor.status,
                provider=self.descriptor,
                executed=False,
                storage_ready=False,
                object_handle=None,
                metadata={
                    **result.metadata,
                    "dry_run_prepared": True,
                    "storage_execution_blocked": True,
                    "real_storage_operations_enabled": False,
                    "missing_configuration_reason": self.descriptor.missing_configuration_reason,
                    "required_configuration_keys": list(self.descriptor.required_configuration_keys),
                },
                required_next_step="complete_storage_provider_configuration",
            )
        return StorageOperationResult(
            operation=request.operation,
            status="dry_run_prepared",
            provider=self.descriptor,
            executed=False,
            storage_ready=True,
            object_handle=None,
            metadata={
                "requested_by": request.requested_by,
                "descriptor": dict(request.descriptor),
                "operation_request": request.as_dict(),
                "dry_run_prepared": True,
                "real_storage_operations_enabled": False,
            },
            required_next_step=None,
        )

    def create_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def upload_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def delete_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def get_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def head_object(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def generate_download(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)

    def generate_upload(self, request: StorageOperationRequest) -> StorageOperationResult:
        return self._result(request)
