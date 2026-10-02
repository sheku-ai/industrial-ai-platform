from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai import Model, ModelProviderValidationEvidence, Provider
from app.models.audit import AuditEvent, AuditHistory
from app.providers.base import ProviderAdapter, ProviderCapabilities
from app.providers.registry import ProviderAdapterRegistry
from app.repositories.ai_configuration import AIConfigurationRepository
from app.schemas.ai_configuration import (
    AI_MODEL_CAPABILITIES,
    ModelConfigurationCreate,
    ModelConfigurationUpdate,
    ProviderConfigurationCreate,
    ProviderConfigurationUpdate,
)
from app.secret_refs.base import SecretReference
from app.secret_refs.environment import EnvironmentSecretResolver
from app.secret_refs.registry import SecretResolverRegistry

READ_PERMISSION = "ai.configuration:read"
PROVIDER_ADMIN_PERMISSION = "ai.providers:administer"
MODEL_ADMIN_PERMISSION = "ai.models:administer"
VALIDATE_PERMISSION = "ai.validation:execute"
SENSITIVE_FRAGMENTS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
ERROR_MESSAGES = {
    "provider_adapter_not_executable": (
        "No executable runtime adapter is registered for this provider type."
    ),
    "provider_validation_required_before_enable": (
        "Enable requires a current successful provider validation."
    ),
    "provider_not_available_for_model": (
        "The model cannot be enabled until its provider is runtime-available."
    ),
    "provider_not_available_for_model_validation": (
        "The model cannot be validated until its provider is runtime-available."
    ),
    "model_not_available_for_default": (
        "The model cannot become default until it is enabled and runtime-available."
    ),
}


class AIConfigurationError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message or ERROR_MESSAGES.get(
            code,
            code.replace("_", " ").capitalize() + ".",
        )


@lru_cache
def get_provider_adapter_registry() -> ProviderAdapterRegistry:
    return ProviderAdapterRegistry()


@lru_cache
def get_secret_resolver_registry() -> SecretResolverRegistry:
    registry = SecretResolverRegistry()
    registry.register(EnvironmentSecretResolver())
    return registry


def _now() -> datetime:
    return datetime.now(UTC)


def _revision(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS):
                continue
            sanitized[str(key)] = _safe_metadata(nested)
        return sanitized
    if isinstance(value, list | tuple):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _public_endpoint_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        return None
    return value


def _adapter_capability_supported(
    capabilities: ProviderCapabilities,
    capability: str,
) -> bool:
    normalized = capability.casefold()
    if normalized in {"generation", "chat"}:
        return capabilities.generation
    if normalized == "embeddings":
        return capabilities.embeddings
    return bool(capabilities.metadata.get(normalized))


class AIConfigurationService:
    def __init__(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID,
        actor_reference: str,
        actor_permissions: frozenset[str],
        correlation_id: str | None,
        adapter_registry: ProviderAdapterRegistry | None = None,
        secret_registry: SecretResolverRegistry | None = None,
    ) -> None:
        self.db = db
        self.organization_id = organization_id
        self.actor_reference = actor_reference
        self.actor_permissions = actor_permissions
        self.correlation_id = correlation_id
        self.repository = AIConfigurationRepository(db, organization_id)
        self.adapter_registry = adapter_registry or get_provider_adapter_registry()
        self.secret_registry = secret_registry or get_secret_resolver_registry()

    def workspace(self) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        providers = self.repository.list_providers()
        models = self.repository.list_models()
        provider_rows = [self._provider_read(item) for item in providers]
        model_rows = [self._model_read(item) for item in models]
        return {
            "capabilities": {
                "read": True,
                "administer_providers": PROVIDER_ADMIN_PERMISSION in self.actor_permissions,
                "administer_models": MODEL_ADMIN_PERMISSION in self.actor_permissions,
                "validate": VALIDATE_PERMISSION in self.actor_permissions,
            },
            "adapters": self.adapters(),
            "model_capabilities": list(AI_MODEL_CAPABILITIES),
            "credential_resolver_types": [
                resolver_type
                for resolver_type in self.secret_registry.registered_types()
                if resolver_type != "disabled"
            ],
            "providers": provider_rows,
            "models": model_rows,
            "provider_count": len(provider_rows),
            "model_count": len(model_rows),
            "available_provider_count": sum(bool(item["available"]) for item in provider_rows),
            "available_model_count": sum(bool(item["available"]) for item in model_rows),
            "ai_required": False,
            "postgresql_source_of_truth": True,
            "secrets_exposed": False,
        }

    def adapters(self) -> list[dict[str, Any]]:
        self._require(READ_PERMISSION)
        rows: list[dict[str, Any]] = []
        for adapter_type in self.adapter_registry.registered_types():
            adapter = self.adapter_registry.resolve(adapter_type)
            capabilities = adapter.capabilities()
            execution_supported = self._adapter_execution_enabled(adapter_type)
            supported = [
                capability
                for capability in AI_MODEL_CAPABILITIES
                if _adapter_capability_supported(capabilities, capability)
            ]
            rows.append(
                {
                    "adapter_type": adapter_type,
                    "supported_capabilities": supported,
                    "credential_required": bool(
                        capabilities.metadata.get("credential_required")
                    ),
                    "known_type": True,
                    "configuration_supported": True,
                    "execution_supported": execution_supported,
                    "availability_reason_code": (
                        None
                        if execution_supported
                        else "provider_adapter_not_executable"
                    ),
                    "availability_reason": (
                        None
                        if execution_supported
                        else ERROR_MESSAGES["provider_adapter_not_executable"]
                    ),
                }
            )
        return rows

    def list_providers(
        self,
        *,
        enabled: bool | None = None,
        lifecycle_status: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require(READ_PERMISSION)
        return [
            self._provider_read(item)
            for item in self.repository.list_providers(
                enabled=enabled,
                lifecycle_status=lifecycle_status,
            )
        ]

    def get_provider(self, provider_id: uuid.UUID) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        return self._provider_read(self._provider(provider_id))

    def create_provider(
        self,
        payload: ProviderConfigurationCreate,
    ) -> dict[str, Any]:
        self._require(PROVIDER_ADMIN_PERMISSION)
        self._adapter(payload.adapter_type)
        if payload.credential is not None:
            self._credential_resolver(payload.credential.resolver_type)
        if self.repository.get_provider_by_key(payload.provider_key) is not None:
            raise AIConfigurationError(409, "provider_key_conflict")
        if payload.enabled:
            raise AIConfigurationError(409, "provider_validation_required_before_enable")

        item = Provider(
            organization_id=self.organization_id,
            provider_key=payload.provider_key,
            display_name=payload.display_name.strip(),
            adapter_type=payload.adapter_type,
            provider_type=payload.adapter_type,
            description=payload.description,
            endpoint_url=payload.endpoint_url,
            credential_resolver_type=(
                payload.credential.resolver_type if payload.credential else None
            ),
            credential_reference=(
                payload.credential.reference if payload.credential else None
            ),
            status="configured",
            enabled=False,
            lifecycle_status="active",
            configuration=payload.configuration,
            capabilities=self._capability_payload(payload.adapter_type),
            health_state="never_validated",
            metadata_json={},
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        item.configuration_revision = self._provider_revision(item)
        self.repository.add(item)
        self.repository.flush()
        self._audit("ai.provider_configuration", item.id, "created", after=self._provider_state(item))
        self._commit(item)
        return self._provider_read(item)

    def update_provider(
        self,
        provider_id: uuid.UUID,
        payload: ProviderConfigurationUpdate,
    ) -> dict[str, Any]:
        self._require(PROVIDER_ADMIN_PERMISSION)
        item = self._provider(provider_id, for_update=True)
        self._require_active(item.lifecycle_status, "provider")
        before = self._provider_state(item)
        previous_revision = item.configuration_revision
        changed = payload.model_dump(exclude_unset=True)
        for field in ("display_name", "description", "endpoint_url", "configuration"):
            if field in changed:
                setattr(item, field, changed[field])
        if payload.credential is not None:
            self._credential_resolver(payload.credential.resolver_type)
            item.credential_resolver_type = payload.credential.resolver_type
            item.credential_reference = payload.credential.reference
        elif payload.clear_credential:
            item.credential_resolver_type = None
            item.credential_reference = None
        item.updated_by = self.actor_reference
        item.configuration_revision = self._provider_revision(item)
        if item.configuration_revision != previous_revision:
            item.enabled = False
        self.repository.add(item)
        self._audit("ai.provider_configuration", item.id, "updated", before, self._provider_state(item))
        self._commit(item)
        return self._provider_read(item)

    def set_provider_enabled(
        self,
        provider_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> dict[str, Any]:
        self._require(PROVIDER_ADMIN_PERMISSION)
        item = self._provider(provider_id, for_update=True)
        self._require_active(item.lifecycle_status, "provider")
        if item.enabled == enabled:
            return self._provider_read(item)
        if not enabled and any(
            model.enabled for model in self.repository.active_models_for_provider(item.id)
        ):
            raise AIConfigurationError(409, "provider_has_enabled_models")
        if enabled:
            if not self._adapter_execution_enabled(item.adapter_type):
                raise AIConfigurationError(409, "provider_adapter_not_executable")
            evidence = self.repository.latest_evidence(provider_id=item.id)
            if not (
                self._adapter_execution_enabled(item.adapter_type)
                and evidence is not None
                and evidence.status == "succeeded"
                and evidence.configuration_revision == item.configuration_revision
            ):
                raise AIConfigurationError(409, "provider_validation_required_before_enable")
        before = self._provider_state(item)
        item.enabled = enabled
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            "ai.provider_configuration",
            item.id,
            "enabled" if enabled else "disabled",
            before,
            self._provider_state(item),
        )
        self._commit(item)
        return self._provider_read(item)

    def archive_provider(self, provider_id: uuid.UUID) -> dict[str, Any]:
        self._require(PROVIDER_ADMIN_PERMISSION)
        item = self._provider(provider_id, for_update=True)
        if item.lifecycle_status == "archived":
            return self._provider_read(item)
        if self.repository.active_models_for_provider(item.id):
            raise AIConfigurationError(409, "provider_has_active_models")
        before = self._provider_state(item)
        item.lifecycle_status = "archived"
        item.enabled = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit("ai.provider_configuration", item.id, "archived", before, self._provider_state(item))
        self._commit(item)
        return self._provider_read(item)

    def restore_provider(self, provider_id: uuid.UUID) -> dict[str, Any]:
        self._require(PROVIDER_ADMIN_PERMISSION)
        item = self._provider(provider_id, for_update=True)
        if item.lifecycle_status == "active":
            return self._provider_read(item)
        before = self._provider_state(item)
        item.lifecycle_status = "active"
        item.enabled = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit("ai.provider_configuration", item.id, "restored", before, self._provider_state(item))
        self._commit(item)
        return self._provider_read(item)

    def validate_provider(self, provider_id: uuid.UUID) -> dict[str, Any]:
        self._require(VALIDATE_PERMISSION)
        item = self._provider(provider_id, for_update=True)
        self._require_active(item.lifecycle_status, "provider")
        if not self._adapter_execution_enabled(item.adapter_type):
            raise AIConfigurationError(409, "provider_adapter_not_executable")
        if item.adapter_type not in self.adapter_registry.registered_types():
            status_value = "failed"
            error_code = "unsupported_provider_adapter"
            sanitized_error = "The configured provider adapter is not registered."
            metadata = {
                "adapter_type": item.adapter_type,
                "adapter_registered": False,
            }
        else:
            adapter = self.adapter_registry.resolve(item.adapter_type)
            (
                status_value,
                error_code,
                sanitized_error,
                metadata,
            ) = self._validate_adapter(item, adapter)
        evidence = self._evidence(
            subject_type="provider",
            provider_id=item.id,
            model_id=None,
            configuration_revision=item.configuration_revision,
            status_value=status_value,
            error_code=error_code,
            sanitized_error=sanitized_error,
            metadata=metadata,
        )
        item.health_state = "healthy" if status_value == "succeeded" else "unavailable"
        if status_value != "succeeded":
            item.enabled = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self.repository.add(evidence)
        self._audit(
            "ai.provider_validation",
            item.id,
            "validation_succeeded" if status_value == "succeeded" else "validation_failed",
            after={
                "status": status_value,
                "error_code": error_code,
                "configuration_revision": item.configuration_revision,
            },
        )
        self._commit(evidence)
        return self._evidence_read(evidence, item.configuration_revision)

    def latest_provider_validation(self, provider_id: uuid.UUID) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        item = self._provider(provider_id)
        evidence = self.repository.latest_evidence(provider_id=item.id)
        if evidence is None:
            raise AIConfigurationError(404, "provider_validation_evidence_not_found")
        return self._evidence_read(evidence, item.configuration_revision)

    def list_models(
        self,
        *,
        provider_id: uuid.UUID | None = None,
        capability: str | None = None,
        enabled: bool | None = None,
        lifecycle_status: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require(READ_PERMISSION)
        return [
            self._model_read(item)
            for item in self.repository.list_models(
                provider_id=provider_id,
                capability=capability,
                enabled=enabled,
                lifecycle_status=lifecycle_status,
            )
        ]

    def get_model(self, model_id: uuid.UUID) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        return self._model_read(self._model(model_id))

    def create_model(self, payload: ModelConfigurationCreate) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        provider = self._provider(payload.provider_configuration_id)
        self._require_active(provider.lifecycle_status, "provider")
        if payload.enabled and not self._provider_availability(provider)["available"]:
            raise AIConfigurationError(409, "provider_not_available_for_model")
        if self.repository.get_model_by_key(payload.model_key) is not None:
            raise AIConfigurationError(409, "model_key_conflict")
        item = Model(
            organization_id=self.organization_id,
            code=payload.model_key,
            name=payload.display_name.strip(),
            provider=provider.provider_key,
            model_name=payload.model_identifier.strip(),
            endpoint=provider.endpoint_url,
            config=payload.configuration,
            status="configured",
            provider_id=provider.id,
            model_key=payload.model_key,
            display_name=payload.display_name.strip(),
            model_ref=payload.model_identifier.strip(),
            model_type=payload.capability,
            capabilities={payload.capability: True},
            configuration=payload.configuration,
            enabled=payload.enabled,
            lifecycle_status="active",
            default_scope=payload.default_scope,
            is_default=False,
            metadata_json={},
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        item.configuration_revision = self._model_revision(item)
        self.repository.add(item)
        self.repository.flush()
        self._audit("ai.model_configuration", item.id, "created", after=self._model_state(item))
        self._commit(item)
        return self._model_read(item)

    def update_model(
        self,
        model_id: uuid.UUID,
        payload: ModelConfigurationUpdate,
    ) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        item = self._model(model_id, for_update=True)
        self._require_active(item.lifecycle_status, "model")
        before = self._model_state(item)
        previous_revision = item.configuration_revision
        changed = payload.model_dump(exclude_unset=True)
        provider = self._provider(
            changed.get("provider_configuration_id") or item.provider_id
        )
        self._require_active(provider.lifecycle_status, "provider")
        if item.enabled and not self._provider_availability(provider)["available"]:
            raise AIConfigurationError(409, "provider_not_available_for_model")
        if "provider_configuration_id" in changed:
            item.provider_id = provider.id
            item.provider = provider.provider_key
            item.endpoint = provider.endpoint_url
        if "display_name" in changed:
            item.display_name = changed["display_name"]
            item.name = changed["display_name"]
        if "model_identifier" in changed:
            item.model_ref = changed["model_identifier"]
            item.model_name = changed["model_identifier"]
        if "capability" in changed:
            item.model_type = changed["capability"]
            item.capabilities = {changed["capability"]: True}
        if "configuration" in changed:
            item.configuration = changed["configuration"]
            item.config = changed["configuration"]
        if "default_scope" in changed:
            item.default_scope = changed["default_scope"]
        if {
            "provider_configuration_id",
            "model_identifier",
            "capability",
            "configuration",
            "default_scope",
        }.intersection(changed):
            item.is_default = False
        item.updated_by = self.actor_reference
        item.configuration_revision = self._model_revision(item)
        if item.configuration_revision != previous_revision:
            item.enabled = False
        self.repository.add(item)
        self._audit("ai.model_configuration", item.id, "updated", before, self._model_state(item))
        self._commit(item)
        return self._model_read(item)

    def set_model_enabled(
        self,
        model_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        item = self._model(model_id, for_update=True)
        self._require_active(item.lifecycle_status, "model")
        if item.enabled == enabled:
            return self._model_read(item)
        provider = self._provider(item.provider_id)
        if enabled and not self._provider_availability(provider)["available"]:
            raise AIConfigurationError(409, "provider_not_available_for_model")
        before = self._model_state(item)
        item.enabled = enabled
        if not enabled:
            item.is_default = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            "ai.model_configuration",
            item.id,
            "enabled" if enabled else "disabled",
            before,
            self._model_state(item),
        )
        self._commit(item)
        return self._model_read(item)

    def archive_model(self, model_id: uuid.UUID) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        item = self._model(model_id, for_update=True)
        if item.lifecycle_status == "archived":
            return self._model_read(item)
        if self.repository.model_reference_count(item.id):
            raise AIConfigurationError(409, "model_has_runtime_references")
        before = self._model_state(item)
        item.lifecycle_status = "archived"
        item.enabled = False
        item.is_default = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit("ai.model_configuration", item.id, "archived", before, self._model_state(item))
        self._commit(item)
        return self._model_read(item)

    def restore_model(self, model_id: uuid.UUID) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        item = self._model(model_id, for_update=True)
        if item.lifecycle_status == "active":
            return self._model_read(item)
        before = self._model_state(item)
        item.lifecycle_status = "active"
        item.enabled = False
        item.is_default = False
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit("ai.model_configuration", item.id, "restored", before, self._model_state(item))
        self._commit(item)
        return self._model_read(item)

    def validate_model(self, model_id: uuid.UUID) -> dict[str, Any]:
        self._require(VALIDATE_PERMISSION)
        item = self._model(model_id, for_update=True)
        self._require_active(item.lifecycle_status, "model")
        provider = self._provider(item.provider_id)
        provider_availability = self._provider_availability(provider)
        if not provider_availability["available"]:
            raise AIConfigurationError(409, "provider_not_available_for_model_validation")
        adapter = self._adapter(provider.adapter_type)
        capabilities = adapter.capabilities()
        supported = _adapter_capability_supported(capabilities, item.model_type or "")
        if not supported:
            status_value = "failed"
            error_code = "model_capability_not_supported"
            sanitized_error = (
                "The configured provider does not support this model capability."
            )
            adapter_metadata: dict[str, Any] = {}
        else:
            (
                status_value,
                error_code,
                sanitized_error,
                adapter_metadata,
            ) = self._validate_adapter(provider, adapter)
        evidence = self._evidence(
            subject_type="model",
            provider_id=None,
            model_id=item.id,
            configuration_revision=item.configuration_revision,
            status_value=status_value,
            error_code=error_code,
            sanitized_error=sanitized_error,
            metadata={
                "adapter_type": provider.adapter_type,
                "capability": item.model_type,
                "model_identifier_present": bool(item.model_ref or item.model_name),
                "provider_validation_current": True,
                **adapter_metadata,
            },
        )
        if status_value != "succeeded":
            item.enabled = False
            item.is_default = False
            item.updated_by = self.actor_reference
            self.repository.add(item)
        self.repository.add(evidence)
        self._audit(
            "ai.model_validation",
            item.id,
            "validation_succeeded" if supported else "validation_failed",
            after={
                "status": status_value,
                "error_code": error_code,
                "configuration_revision": item.configuration_revision,
            },
        )
        self._commit(evidence)
        return self._evidence_read(evidence, item.configuration_revision)

    def latest_model_validation(self, model_id: uuid.UUID) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        item = self._model(model_id)
        evidence = self.repository.latest_evidence(model_id=item.id)
        if evidence is None:
            raise AIConfigurationError(404, "model_validation_evidence_not_found")
        return self._evidence_read(evidence, item.configuration_revision)

    def set_default_model(
        self,
        model_id: uuid.UUID,
        *,
        is_default: bool,
    ) -> dict[str, Any]:
        self._require(MODEL_ADMIN_PERMISSION)
        item = self._model(model_id, for_update=True)
        self._require_active(item.lifecycle_status, "model")
        if item.is_default == is_default:
            return self._model_read(item)
        if is_default and not self._model_availability(item)["available"]:
            raise AIConfigurationError(409, "model_not_available_for_default")
        before = self._model_state(item)
        if is_default:
            self.repository.lock_default_scope(
                capability=item.model_type or "unknown",
                default_scope=item.default_scope,
            )
            self.repository.clear_other_defaults(
                capability=item.model_type or "unknown",
                default_scope=item.default_scope,
                except_model_id=item.id,
            )
        item.is_default = is_default
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            "ai.model_configuration",
            item.id,
            "default_set" if is_default else "default_unset",
            before,
            self._model_state(item),
        )
        self._commit(item)
        return self._model_read(item)

    def _provider(
        self,
        provider_id: uuid.UUID | None,
        *,
        for_update: bool = False,
    ) -> Provider:
        if provider_id is None:
            raise AIConfigurationError(404, "provider_configuration_not_found")
        item = self.repository.get_provider(provider_id, for_update=for_update)
        if item is None:
            raise AIConfigurationError(404, "provider_configuration_not_found")
        return item

    def _model(
        self,
        model_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Model:
        item = self.repository.get_model(model_id, for_update=for_update)
        if item is None:
            raise AIConfigurationError(404, "model_configuration_not_found")
        return item

    def _adapter(self, adapter_type: str) -> ProviderAdapter:
        normalized = adapter_type.strip()
        if normalized not in self.adapter_registry.registered_types():
            raise AIConfigurationError(422, "unsupported_provider_adapter")
        return self.adapter_registry.resolve(normalized)

    def _credential_resolver(self, resolver_type: str):
        normalized = resolver_type.strip()
        if normalized not in self.secret_registry.registered_types():
            raise AIConfigurationError(422, "unsupported_credential_resolver")
        return self.secret_registry.resolve(normalized)

    def _capability_payload(self, adapter_type: str) -> dict[str, Any]:
        capabilities = self._adapter(adapter_type).capabilities()
        return {
            capability: _adapter_capability_supported(capabilities, capability)
            for capability in AI_MODEL_CAPABILITIES
        }

    def _adapter_execution_enabled(self, adapter_type: str) -> bool:
        if adapter_type not in self.adapter_registry.registered_types():
            return False
        adapter = self.adapter_registry.resolve(adapter_type)
        return bool(
            adapter.capabilities().metadata.get(
                "execution_enabled",
                adapter_type != "disabled",
            )
        )

    def _provider_revision(self, item: Provider) -> str:
        return _revision(
            {
                "adapter_type": item.adapter_type,
                "endpoint_url": item.endpoint_url,
                "credential_resolver_type": item.credential_resolver_type,
                "credential_reference": item.credential_reference,
                "configuration": item.configuration or {},
            }
        )

    def _model_revision(self, item: Model) -> str:
        return _revision(
            {
                "provider_id": item.provider_id,
                "model_identifier": item.model_ref or item.model_name,
                "capability": item.model_type,
                "configuration": item.configuration or {},
                "default_scope": item.default_scope,
            }
        )

    def _validate_adapter(
        self,
        provider: Provider,
        adapter: ProviderAdapter,
    ) -> tuple[str, str | None, str | None, dict[str, Any]]:
        capabilities = adapter.capabilities()
        credential_required = bool(capabilities.metadata.get("credential_required"))
        credential_status = "not_required"
        if provider.credential_reference:
            if not provider.credential_resolver_type:
                return (
                    "failed",
                    "credential_resolver_missing",
                    "The credential reference does not identify a resolver.",
                    {"credential_configured": True},
                )
            if (
                provider.credential_resolver_type
                not in self.secret_registry.registered_types()
            ):
                return (
                    "failed",
                    "credential_resolver_unsupported",
                    "The credential reference uses an unsupported resolver.",
                    {
                        "adapter_type": provider.adapter_type,
                        "credential_configured": True,
                    },
                )
            resolver = self.secret_registry.resolve(provider.credential_resolver_type)
            try:
                resolution = resolver.resolve(
                    SecretReference(
                        resolver_type=provider.credential_resolver_type,
                        reference=provider.credential_reference,
                    )
                )
            except Exception as exc:
                return (
                    "failed",
                    "credential_resolution_error",
                    "The credential reference could not be resolved.",
                    {
                        "adapter_type": provider.adapter_type,
                        "credential_configured": True,
                        "error_type": type(exc).__name__,
                    },
                )
            credential_status = resolution.status
            if resolution.status != "resolved" or resolution.value is None:
                return (
                    "failed",
                    resolution.error_code or "credential_reference_unresolved",
                    "The configured credential reference could not be resolved.",
                    {
                        "adapter_type": provider.adapter_type,
                        "credential_configured": True,
                        "credential_resolution_status": resolution.status,
                    },
                )
        elif credential_required:
            return (
                "failed",
                "credential_reference_required",
                "This provider adapter requires a credential reference.",
                {
                    "adapter_type": provider.adapter_type,
                    "credential_configured": False,
                },
            )
        try:
            health = adapter.health_check()
        except Exception as exc:
            return (
                "failed",
                "provider_validation_error",
                "The provider adapter could not complete validation.",
                {
                    "adapter_type": provider.adapter_type,
                    "error_type": type(exc).__name__,
                    "credential_resolution_status": credential_status,
                },
            )
        succeeded = health.status.casefold() in {"available", "healthy", "ready", "succeeded"}
        return (
            "succeeded" if succeeded else "failed",
            None if succeeded else "provider_not_ready",
            None if succeeded else "The provider adapter did not report a ready state.",
            {
                "adapter_type": provider.adapter_type,
                "adapter_health_status": health.status,
                "latency_ms": health.latency_ms,
                "credential_resolution_status": credential_status,
                "credential_value_persisted": False,
                **_safe_metadata(dict(health.metadata)),
            },
        )

    def _provider_availability(self, item: Provider) -> dict[str, Any]:
        evidence = self.repository.latest_evidence(provider_id=item.id)
        current = bool(
            evidence is not None
            and evidence.configuration_revision == item.configuration_revision
        )
        succeeded = bool(current and evidence and evidence.status == "succeeded")
        adapter_available = self._adapter_execution_enabled(item.adapter_type)
        available = bool(
            item.lifecycle_status == "active"
            and item.enabled
            and adapter_available
            and succeeded
        )
        if item.lifecycle_status != "active":
            status_value = "archived"
        elif not item.enabled:
            status_value = "disabled"
        elif not adapter_available:
            status_value = "adapter_unavailable"
        elif evidence is None:
            status_value = "never_validated"
        elif not current:
            status_value = "validation_stale"
        elif evidence.status != "succeeded":
            status_value = "validation_failed"
        else:
            status_value = "available"
        return {
            "available": available,
            "status": status_value,
            "evidence": evidence,
            "reason_code": (
                None
                if available
                else {
                    "archived": "provider_configuration_archived",
                    "disabled": "provider_configuration_disabled",
                    "adapter_unavailable": "provider_adapter_not_executable",
                    "never_validated": "provider_never_validated",
                    "validation_stale": "provider_validation_stale",
                    "validation_failed": "provider_validation_failed",
                }[status_value]
            ),
            "reason": None if available else self._provider_unavailability_reason(
                status_value
            ),
        }

    def _model_availability(self, item: Model) -> dict[str, Any]:
        evidence = self.repository.latest_evidence(model_id=item.id)
        current = bool(
            evidence is not None
            and evidence.configuration_revision == item.configuration_revision
        )
        provider = self._provider(item.provider_id)
        provider_availability = self._provider_availability(provider)
        provider_available = provider_availability["available"]
        available = bool(
            item.lifecycle_status == "active"
            and item.enabled
            and provider_available
            and current
            and evidence
            and evidence.status == "succeeded"
        )
        if item.lifecycle_status != "active":
            status_value = "archived"
        elif not item.enabled:
            status_value = "disabled"
        elif not provider_available:
            status_value = "provider_unavailable"
        elif evidence is None:
            status_value = "never_validated"
        elif not current:
            status_value = "validation_stale"
        elif evidence.status != "succeeded":
            status_value = "validation_failed"
        else:
            status_value = "available"
        return {
            "available": available,
            "status": status_value,
            "evidence": evidence,
            "reason_code": (
                None
                if available
                else {
                    "archived": "model_configuration_archived",
                    "disabled": "model_configuration_disabled",
                    "provider_unavailable": provider_availability["reason_code"],
                    "never_validated": "model_never_validated",
                    "validation_stale": "model_validation_stale",
                    "validation_failed": "model_validation_failed",
                }[status_value]
            ),
            "reason": (
                None
                if available
                else provider_availability["reason"]
                if status_value == "provider_unavailable"
                else self._model_unavailability_reason(status_value)
            ),
        }

    def _validation_status(
        self,
        evidence: ModelProviderValidationEvidence | None,
        current_revision: str,
    ) -> str:
        if evidence is None:
            return "never_validated"
        if evidence.configuration_revision != current_revision:
            return "stale"
        return evidence.status

    def _provider_unavailability_reason(self, status_value: str) -> str:
        return {
            "archived": "The provider configuration is archived.",
            "disabled": "The provider configuration is disabled.",
            "adapter_unavailable": ERROR_MESSAGES[
                "provider_adapter_not_executable"
            ],
            "never_validated": "The provider has never been validated.",
            "validation_stale": (
                "The provider configuration changed after its latest validation."
            ),
            "validation_failed": "The latest provider validation failed.",
        }[status_value]

    def _model_unavailability_reason(self, status_value: str) -> str:
        return {
            "archived": "The model configuration is archived.",
            "disabled": "The model configuration is disabled.",
            "never_validated": "The model has never been validated.",
            "validation_stale": (
                "The model configuration changed after its latest validation."
            ),
            "validation_failed": "The latest model validation failed.",
        }[status_value]

    def _action(
        self,
        *,
        allowed: bool,
        reason_code: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "reason_code": None if allowed else reason_code,
            "reason": None if allowed else reason,
        }

    def _provider_runtime_actions(
        self,
        item: Provider,
        availability: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        active = item.lifecycle_status == "active"
        adapter_executable = self._adapter_execution_enabled(item.adapter_type)
        validate_reason_code = (
            "provider_configuration_archived"
            if not active
            else "provider_adapter_not_executable"
        )
        validate_reason = (
            "The provider configuration is archived."
            if not active
            else ERROR_MESSAGES["provider_adapter_not_executable"]
        )
        can_validate = active and adapter_executable

        can_toggle_enabled = active and (
            item.enabled
            or (
                adapter_executable
                and availability["evidence"] is not None
                and availability["evidence"].status == "succeeded"
                and availability["evidence"].configuration_revision
                == item.configuration_revision
            )
        )
        if not active:
            enable_reason_code = "provider_configuration_archived"
            enable_reason = "The provider configuration is archived."
        elif not adapter_executable:
            enable_reason_code = "provider_adapter_not_executable"
            enable_reason = ERROR_MESSAGES["provider_adapter_not_executable"]
        else:
            enable_reason_code = "provider_validation_required_before_enable"
            enable_reason = ERROR_MESSAGES[
                "provider_validation_required_before_enable"
            ]
        return {
            "validate": self._action(
                allowed=can_validate,
                reason_code=validate_reason_code,
                reason=validate_reason,
            ),
            "enable": self._action(
                allowed=can_toggle_enabled,
                reason_code=enable_reason_code,
                reason=enable_reason,
            ),
        }

    def _model_runtime_actions(
        self,
        item: Model,
        availability: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        active = item.lifecycle_status == "active"
        provider = self._provider(item.provider_id)
        provider_availability = self._provider_availability(provider)
        provider_available = provider_availability["available"]

        if not active:
            runtime_reason_code = "model_configuration_archived"
            runtime_reason = "The model configuration is archived."
        elif not self._adapter_execution_enabled(provider.adapter_type):
            runtime_reason_code = "provider_adapter_not_executable"
            runtime_reason = ERROR_MESSAGES["provider_adapter_not_executable"]
        else:
            runtime_reason_code = (
                provider_availability["reason_code"]
                or "provider_not_available_for_model"
            )
            runtime_reason = (
                provider_availability["reason"]
                or ERROR_MESSAGES["provider_not_available_for_model"]
            )
        can_toggle_enabled = active and (item.enabled or provider_available)
        can_validate = active and provider_available
        can_set_default = active and (
            bool(item.is_default) or availability["available"]
        )
        return {
            "enable": self._action(
                allowed=can_toggle_enabled,
                reason_code=runtime_reason_code,
                reason=runtime_reason,
            ),
            "validate": self._action(
                allowed=can_validate,
                reason_code=runtime_reason_code,
                reason=runtime_reason,
            ),
            "set_default": self._action(
                allowed=can_set_default,
                reason_code=(
                    runtime_reason_code
                    if not provider_available
                    else "model_not_available_for_default"
                ),
                reason=(
                    runtime_reason
                    if not provider_available
                    else ERROR_MESSAGES["model_not_available_for_default"]
                ),
            ),
        }

    def _provider_read(self, item: Provider) -> dict[str, Any]:
        availability = self._provider_availability(item)
        evidence = availability["evidence"]
        return {
            "id": item.id,
            "organization_id": item.organization_id,
            "provider_key": item.provider_key,
            "display_name": item.display_name,
            "adapter_type": item.adapter_type,
            "provider_type": item.provider_type,
            "description": item.description,
            "endpoint_url": _public_endpoint_url(item.endpoint_url),
            "configuration": _safe_metadata(item.configuration or {}),
            "enabled": item.enabled,
            "lifecycle_status": item.lifecycle_status,
            "credential_configured": bool(item.credential_reference),
            "availability_status": availability["status"],
            "available": availability["available"],
            "validation_status": self._validation_status(
                evidence,
                item.configuration_revision,
            ),
            "latest_validation": (
                self._evidence_read(evidence, item.configuration_revision)
                if evidence
                else None
            ),
            "runtime_actions": self._provider_runtime_actions(
                item,
                availability,
            ),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "created_by": item.created_by,
            "updated_by": item.updated_by,
        }

    def _model_read(self, item: Model) -> dict[str, Any]:
        provider = self._provider(item.provider_id)
        availability = self._model_availability(item)
        evidence = availability["evidence"]
        return {
            "id": item.id,
            "organization_id": item.organization_id,
            "provider_configuration_id": provider.id,
            "provider_display_name": provider.display_name,
            "model_key": item.model_key or item.code,
            "display_name": item.display_name or item.name,
            "model_identifier": item.model_ref or item.model_name,
            "capability": item.model_type or "generation",
            "configuration": _safe_metadata(item.configuration or {}),
            "enabled": item.enabled,
            "lifecycle_status": item.lifecycle_status,
            "default_scope": item.default_scope,
            "is_default": bool(item.is_default),
            "default_effective": bool(item.is_default and availability["available"]),
            "availability_status": availability["status"],
            "available": availability["available"],
            "validation_status": self._validation_status(
                evidence,
                item.configuration_revision,
            ),
            "latest_validation": (
                self._evidence_read(evidence, item.configuration_revision)
                if evidence
                else None
            ),
            "runtime_actions": self._model_runtime_actions(
                item,
                availability,
            ),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "created_by": item.created_by,
            "updated_by": item.updated_by,
        }

    def _evidence(
        self,
        *,
        subject_type: str,
        provider_id: uuid.UUID | None,
        model_id: uuid.UUID | None,
        configuration_revision: str,
        status_value: str,
        error_code: str | None,
        sanitized_error: str | None,
        metadata: dict[str, Any],
    ) -> ModelProviderValidationEvidence:
        return ModelProviderValidationEvidence(
            organization_id=self.organization_id,
            provider_id=provider_id,
            model_id=model_id,
            subject_type=subject_type,
            validation_type="adapter_configuration",
            status=status_value,
            configuration_revision=configuration_revision,
            error_code=error_code,
            sanitized_error=sanitized_error,
            evidence_metadata=_safe_metadata(metadata),
            evaluated_at=_now(),
            actor_reference=self.actor_reference,
            correlation_id=self.correlation_id,
        )

    def _evidence_read(
        self,
        evidence: ModelProviderValidationEvidence,
        current_revision: str,
    ) -> dict[str, Any]:
        return {
            "id": evidence.id,
            "subject_type": evidence.subject_type,
            "validation_type": evidence.validation_type,
            "status": evidence.status,
            "error_code": evidence.error_code,
            "sanitized_error": evidence.sanitized_error,
            "evaluated_at": evidence.evaluated_at,
            "configuration_revision": evidence.configuration_revision,
            "current_configuration_revision": current_revision,
            "evidence_status": (
                "current"
                if evidence.configuration_revision == current_revision
                else "stale"
            ),
            "actor_reference": evidence.actor_reference,
            "correlation_id": evidence.correlation_id,
            "metadata": _safe_metadata(evidence.evidence_metadata or {}),
        }

    def _provider_state(self, item: Provider) -> dict[str, Any]:
        return {
            "provider_key": item.provider_key,
            "display_name": item.display_name,
            "adapter_type": item.adapter_type,
            "endpoint_configured": bool(item.endpoint_url),
            "credential_configured": bool(item.credential_reference),
            "credential_resolver_type": (
                item.credential_resolver_type if item.credential_reference else None
            ),
            "configuration_keys": sorted((item.configuration or {}).keys()),
            "enabled": item.enabled,
            "lifecycle_status": item.lifecycle_status,
            "configuration_revision": item.configuration_revision,
        }

    def _model_state(self, item: Model) -> dict[str, Any]:
        return {
            "provider_id": str(item.provider_id) if item.provider_id else None,
            "model_key": item.model_key or item.code,
            "display_name": item.display_name or item.name,
            "model_identifier_configured": bool(item.model_ref or item.model_name),
            "capability": item.model_type,
            "configuration_keys": sorted((item.configuration or {}).keys()),
            "enabled": item.enabled,
            "lifecycle_status": item.lifecycle_status,
            "default_scope": item.default_scope,
            "is_default": item.is_default,
            "configuration_revision": item.configuration_revision,
        }

    def _audit(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        safe_before = _safe_metadata(before or {})
        safe_after = _safe_metadata(after or {})
        self.repository.add(
            AuditEvent(
                organization_id=self.organization_id,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type=resource_type,
                resource_id=str(resource_id),
                summary=action,
                metadata_json={
                    "action": action,
                    "correlation_id": self.correlation_id,
                    "postgresql_source_of_truth": True,
                    "secrets_exposed": False,
                },
            )
        )
        self.repository.add(
            AuditHistory(
                organization_id=self.organization_id,
                entity_type=resource_type,
                entity_id=str(resource_id),
                action=action,
                before_state=safe_before,
                after_state=safe_after,
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _commit(self, item: object) -> None:
        try:
            self.repository.commit()
            self.repository.refresh(item)
        except IntegrityError as exc:
            self.repository.rollback()
            raise AIConfigurationError(409, "ai_configuration_conflict") from exc

    def _require(self, permission: str) -> None:
        if permission not in self.actor_permissions:
            raise AIConfigurationError(403, "ai_configuration_permission_required")

    def _require_active(self, lifecycle_status: str, subject: str) -> None:
        if lifecycle_status != "active":
            raise AIConfigurationError(409, f"{subject}_configuration_archived")
