from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

AI_MODEL_CAPABILITIES = (
    "generation",
    "chat",
    "embeddings",
    "reranking",
    "multimodal",
)
SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
SAFE_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")


def _reject_secret_configuration(value: Any) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().casefold()
            if any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS):
                raise ValueError("secret values must be supplied through a credential reference")
            _reject_secret_configuration(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_configuration(nested)
    return value


def _validate_endpoint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint URL must use http or https and include a host")
    if parsed.username or parsed.password:
        raise ValueError("endpoint URL must not contain credentials")
    return normalized.rstrip("/")


class CredentialReferenceInput(BaseModel):
    resolver_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    reference: str = Field(min_length=1, max_length=1024)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not SAFE_KEY_PATTERN.fullmatch(normalized):
            raise ValueError("credential reference must be an external resolver key")
        return normalized


class ProviderConfigurationCreate(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=255)
    adapter_type: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    credential: CredentialReferenceInput | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False

    _safe_configuration = field_validator("configuration")(_reject_secret_configuration)
    _safe_endpoint = field_validator("endpoint_url")(_validate_endpoint)


class ProviderConfigurationUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    credential: CredentialReferenceInput | None = None
    clear_credential: bool = False
    configuration: dict[str, Any] | None = None

    _safe_configuration = field_validator("configuration")(_reject_secret_configuration)
    _safe_endpoint = field_validator("endpoint_url")(_validate_endpoint)

    @model_validator(mode="after")
    def validate_credential_change(self) -> ProviderConfigurationUpdate:
        if self.credential is not None and self.clear_credential:
            raise ValueError("credential and clear_credential cannot be supplied together")
        return self


class ValidationEvidenceRead(BaseModel):
    id: uuid.UUID
    subject_type: Literal["provider", "model"]
    validation_type: str
    status: Literal["succeeded", "failed"]
    error_code: str | None = None
    sanitized_error: str | None = None
    evaluated_at: datetime
    configuration_revision: str
    current_configuration_revision: str
    evidence_status: Literal["current", "stale"]
    actor_reference: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeActionAvailabilityRead(BaseModel):
    allowed: bool
    reason_code: str | None = None
    reason: str | None = None


class ProviderConfigurationRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider_key: str
    display_name: str
    adapter_type: str
    provider_type: str
    description: str | None = None
    endpoint_url: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    lifecycle_status: Literal["active", "archived"]
    credential_configured: bool
    availability_status: str
    available: bool
    validation_status: Literal["never_validated", "succeeded", "failed", "stale"]
    latest_validation: ValidationEvidenceRead | None = None
    runtime_actions: dict[str, RuntimeActionAvailabilityRead] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ModelConfigurationCreate(BaseModel):
    provider_configuration_id: uuid.UUID
    model_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=255)
    model_identifier: str = Field(min_length=1, max_length=255)
    capability: Literal["generation", "chat", "embeddings", "reranking", "multimodal"]
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    default_scope: str = Field(default="organization", min_length=1, max_length=64)

    _safe_configuration = field_validator("configuration")(_reject_secret_configuration)


class ModelConfigurationUpdate(BaseModel):
    provider_configuration_id: uuid.UUID | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    model_identifier: str | None = Field(default=None, min_length=1, max_length=255)
    capability: Literal["generation", "chat", "embeddings", "reranking", "multimodal"] | None = None
    configuration: dict[str, Any] | None = None
    default_scope: str | None = Field(default=None, min_length=1, max_length=64)

    _safe_configuration = field_validator("configuration")(_reject_secret_configuration)


class ModelConfigurationRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider_configuration_id: uuid.UUID
    provider_display_name: str
    model_key: str
    display_name: str
    model_identifier: str
    capability: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    lifecycle_status: Literal["active", "archived"]
    default_scope: str
    is_default: bool
    default_effective: bool
    availability_status: str
    available: bool
    validation_status: Literal["never_validated", "succeeded", "failed", "stale"]
    latest_validation: ValidationEvidenceRead | None = None
    runtime_actions: dict[str, RuntimeActionAvailabilityRead] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ProviderAdapterRead(BaseModel):
    adapter_type: str
    supported_capabilities: list[str] = Field(default_factory=list)
    credential_required: bool
    known_type: bool = True
    configuration_supported: bool = True
    execution_supported: bool
    availability_reason_code: str | None = None
    availability_reason: str | None = None


class AIConfigurationWorkspaceRead(BaseModel):
    capabilities: dict[str, bool] = Field(default_factory=dict)
    adapters: list[ProviderAdapterRead] = Field(default_factory=list)
    model_capabilities: list[str] = Field(default_factory=list)
    credential_resolver_types: list[str] = Field(default_factory=list)
    providers: list[ProviderConfigurationRead] = Field(default_factory=list)
    models: list[ModelConfigurationRead] = Field(default_factory=list)
    provider_count: int
    model_count: int
    available_provider_count: int
    available_model_count: int
    ai_required: bool = False
    postgresql_source_of_truth: bool = True
    secrets_exposed: bool = False


class EnabledStateRequest(BaseModel):
    enabled: bool


class DefaultStateRequest(BaseModel):
    is_default: bool
