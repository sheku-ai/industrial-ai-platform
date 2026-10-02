from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.ai import Model, ModelProviderValidationEvidence, Provider
from app.models.audit import AuditEvent, AuditHistory
from app.models.security import Permission
from app.providers.base import ProviderCapabilities, ProviderHealth
from app.providers.registry import ProviderAdapterRegistry
from app.schemas.ai_configuration import (
    ModelConfigurationCreate,
    ModelConfigurationUpdate,
    ProviderConfigurationCreate,
    ProviderConfigurationUpdate,
)
from app.secret_refs.base import SecretResolutionResult, SecretValue
from app.secret_refs.registry import SecretResolverRegistry
from app.security.api_policy import required_permissions
from app.services.ai_configuration import AIConfigurationError, AIConfigurationService
from app.services.organization_access_management import (
    OrganizationAccessError,
    OrganizationAccessManagementService,
)
from app.services.reference_tenant import REFERENCE_PERMISSIONS

ALL_PERMISSIONS = frozenset(
    {
        "ai.configuration:read",
        "ai.providers:administer",
        "ai.models:administer",
        "ai.validation:execute",
    }
)


class _HealthyAdapter:
    adapter_type = "test-healthy"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            generation=True,
            embeddings=True,
            metadata={
                "credential_required": True,
                "execution_enabled": True,
            },
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status="healthy",
            latency_ms=3,
            metadata={"region": "test", "token": "must-not-be-persisted"},
        )


class _FailingAdapter:
    adapter_type = "test-failing"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            generation=True,
            metadata={"execution_enabled": True},
        )

    def health_check(self) -> ProviderHealth:
        raise RuntimeError("provider response containing sensitive material")


class _SecretResolver:
    resolver_type = "test-secret"

    def resolve(self, _reference) -> SecretResolutionResult:
        return SecretResolutionResult(
            status="resolved",
            value=SecretValue("credential-value-must-not-escape"),
        )


class _FakeRepository:
    def __init__(self, organization_id: uuid.UUID) -> None:
        self.organization_id = organization_id
        self.providers: dict[uuid.UUID, Provider] = {}
        self.models: dict[uuid.UUID, Model] = {}
        self.evidence: list[ModelProviderValidationEvidence] = []
        self.audit: list[AuditEvent | AuditHistory] = []
        self.references: set[uuid.UUID] = set()
        self.commit_count = 0
        self.default_lock_count = 0

    def _owned(self, item: Any) -> bool:
        return item.organization_id == self.organization_id

    def list_providers(self, **filters) -> list[Provider]:
        return [
            item
            for item in self.providers.values()
            if self._owned(item)
            and all(
                value is None or getattr(item, key) == value
                for key, value in filters.items()
            )
        ]

    def get_provider(self, provider_id, *, for_update=False):
        item = self.providers.get(provider_id)
        return item if item is not None and self._owned(item) else None

    def get_provider_by_key(self, provider_key):
        return next(
            (
                item
                for item in self.providers.values()
                if self._owned(item) and item.provider_key == provider_key
            ),
            None,
        )

    def list_models(self, **filters) -> list[Model]:
        attribute_names = {"provider_id": "provider_id", "capability": "model_type"}
        return [
            item
            for item in self.models.values()
            if self._owned(item)
            and all(
                value is None
                or getattr(item, attribute_names.get(key, key)) == value
                for key, value in filters.items()
            )
        ]

    def get_model(self, model_id, *, for_update=False):
        item = self.models.get(model_id)
        return item if item is not None and self._owned(item) else None

    def get_model_by_key(self, model_key):
        return next(
            (
                item
                for item in self.models.values()
                if self._owned(item) and item.model_key == model_key
            ),
            None,
        )

    def active_models_for_provider(self, provider_id):
        return [
            item
            for item in self.models.values()
            if self._owned(item)
            and item.provider_id == provider_id
            and item.lifecycle_status == "active"
        ]

    def model_reference_count(self, model_id):
        return int(model_id in self.references)

    def latest_evidence(self, *, provider_id=None, model_id=None):
        matches = [
            item
            for item in self.evidence
            if self._owned(item)
            and (
                (provider_id is not None and item.provider_id == provider_id)
                or (model_id is not None and item.model_id == model_id)
            )
        ]
        return matches[-1] if matches else None

    def clear_other_defaults(
        self,
        *,
        capability,
        default_scope,
        except_model_id=None,
    ):
        for item in self.models.values():
            if (
                self._owned(item)
                and item.model_type == capability
                and item.default_scope == default_scope
                and item.id != except_model_id
            ):
                item.is_default = False

    def lock_default_scope(self, **_scope):
        self.default_lock_count += 1

    def add(self, item):
        now = datetime.now(UTC)
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        if getattr(item, "created_at", None) is None:
            item.created_at = now
        item.updated_at = now
        if isinstance(item, Provider):
            self.providers[item.id] = item
        elif isinstance(item, Model):
            self.models[item.id] = item
        elif isinstance(item, ModelProviderValidationEvidence):
            if item not in self.evidence:
                self.evidence.append(item)
        elif isinstance(item, AuditEvent | AuditHistory):
            self.audit.append(item)

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        return None

    def refresh(self, _item):
        return None


def _service(
    organization_id: uuid.UUID | None = None,
    *,
    permissions: frozenset[str] = ALL_PERMISSIONS,
) -> tuple[AIConfigurationService, _FakeRepository]:
    organization_id = organization_id or uuid.uuid4()
    adapters = ProviderAdapterRegistry()
    adapters.register(_HealthyAdapter())
    adapters.register(_FailingAdapter())
    secrets = SecretResolverRegistry()
    secrets.register(_SecretResolver())
    service = AIConfigurationService(
        None,  # type: ignore[arg-type]
        organization_id=organization_id,
        actor_reference="authenticated-user",
        actor_permissions=permissions,
        correlation_id="correlation-test",
        adapter_registry=adapters,
        secret_registry=secrets,
    )
    repository = _FakeRepository(organization_id)
    service.repository = repository  # type: ignore[assignment]
    return service, repository


def _provider_payload(
    key: str,
    *,
    adapter_type: str = "test-healthy",
) -> ProviderConfigurationCreate:
    return ProviderConfigurationCreate(
        provider_key=key,
        display_name=key.replace("-", " ").title(),
        adapter_type=adapter_type,
        credential=(
            {
                "resolver_type": "test-secret",
                "reference": "TEST_PROVIDER_CREDENTIAL",
            }
            if adapter_type == "test-healthy"
            else None
        ),
        configuration={"region": "test"},
    )


def _available_provider(service: AIConfigurationService, key: str) -> dict[str, Any]:
    provider = service.create_provider(_provider_payload(key))
    evidence = service.validate_provider(provider["id"])
    assert evidence["status"] == "succeeded"
    return service.set_provider_enabled(provider["id"], enabled=True)


def _available_model(
    service: AIConfigurationService,
    provider_id: uuid.UUID,
    key: str,
) -> dict[str, Any]:
    model = service.create_model(
        ModelConfigurationCreate(
            provider_configuration_id=provider_id,
            model_key=key,
            display_name=key.replace("-", " ").title(),
            model_identifier=f"adapter/{key}",
            capability="generation",
            configuration={"temperature": 0},
            enabled=True,
        )
    )
    evidence = service.validate_model(model["id"])
    assert evidence["status"] == "succeeded"
    return service.get_model(model["id"])


def test_configuration_rejects_secret_fields_and_never_returns_credential_material() -> None:
    with pytest.raises(ValidationError, match="credential reference"):
        ProviderConfigurationCreate(
            provider_key="unsafe",
            display_name="Unsafe",
            adapter_type="test-healthy",
            configuration={"nested": {"api_key": "plain-text"}},
        )

    service, _repository = _service()
    result = service.create_provider(_provider_payload("safe-provider"))
    serialized = json.dumps(result, default=str)

    assert result["credential_configured"] is True
    assert "credential_reference" not in result
    assert "credential_resolver_type" not in result
    assert "credential-value-must-not-escape" not in serialized
    assert "TEST_PROVIDER_CREDENTIAL" not in serialized


def test_validation_history_is_persisted_sanitized_and_becomes_stale() -> None:
    service, repository = _service()
    provider = service.create_provider(_provider_payload("governed-provider"))

    succeeded = service.validate_provider(provider["id"])
    assert succeeded["status"] == "succeeded"
    assert succeeded["metadata"]["region"] == "test"
    assert "token" not in succeeded["metadata"]
    assert len(repository.evidence) == 1

    service.set_provider_enabled(provider["id"], enabled=True)
    updated = service.update_provider(
        provider["id"],
        ProviderConfigurationUpdate(configuration={"region": "changed"}),
    )
    assert updated["validation_status"] == "stale"
    assert updated["available"] is False
    assert len(repository.evidence) == 1

    failed_provider = service.create_provider(
        _provider_payload("failing-provider", adapter_type="test-failing")
    )
    failed = service.validate_provider(failed_provider["id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "provider_validation_error"
    assert "sensitive material" not in json.dumps(failed, default=str)
    assert len(repository.evidence) == 2


def test_disabled_provider_blocks_model_enable_and_validation_and_foreign_provider_is_hidden() -> None:
    organization_id = uuid.uuid4()
    service, repository = _service(organization_id)
    provider = service.create_provider(_provider_payload("disabled-provider"))
    model = service.create_model(
        ModelConfigurationCreate(
            provider_configuration_id=provider["id"],
            model_key="blocked-model",
            display_name="Blocked model",
            model_identifier="adapter/blocked",
            capability="generation",
        )
    )
    assert model["enabled"] is False
    assert model["default_effective"] is False
    assert model["runtime_actions"]["enable"]["allowed"] is False
    assert model["runtime_actions"]["validate"]["allowed"] is False
    assert model["runtime_actions"]["enable"]["reason"]

    with pytest.raises(AIConfigurationError, match="provider_not_available"):
        service.set_model_enabled(model["id"], enabled=True)
    with pytest.raises(AIConfigurationError, match="provider_not_available"):
        service.validate_model(model["id"])

    foreign_service, foreign_repository = _service(uuid.uuid4())
    foreign = foreign_service.create_provider(_provider_payload("foreign-provider"))
    repository.providers[foreign["id"]] = foreign_repository.providers[foreign["id"]]
    with pytest.raises(AIConfigurationError) as exc_info:
        service.create_model(
            ModelConfigurationCreate(
                provider_configuration_id=foreign["id"],
                model_key="foreign-model",
                display_name="Foreign model",
                model_identifier="adapter/foreign",
                capability="generation",
            )
        )
    assert exc_info.value.status_code == 404


def test_configuration_only_adapter_allows_disabled_model_crud_but_blocks_runtime_actions() -> None:
    service, repository = _service()
    adapters = {item["adapter_type"]: item for item in service.adapters()}
    assert adapters["disabled"] == {
        "adapter_type": "disabled",
        "supported_capabilities": [],
        "credential_required": False,
        "known_type": True,
        "configuration_supported": True,
        "execution_supported": False,
        "availability_reason_code": "provider_adapter_not_executable",
        "availability_reason": (
            "No executable runtime adapter is registered for this provider type."
        ),
    }
    assert service.workspace()["model_capabilities"] == [
        "generation",
        "chat",
        "embeddings",
        "reranking",
        "multimodal",
    ]

    provider = service.create_provider(
        _provider_payload("configuration-only-provider", adapter_type="disabled")
    )
    model = service.create_model(
        ModelConfigurationCreate(
            provider_configuration_id=provider["id"],
            model_key="configuration-only-model",
            display_name="Configuration only model",
            model_identifier="future/model",
            capability="chat",
        )
    )
    updated = service.update_model(
        model["id"],
        ModelConfigurationUpdate(
            display_name="Updated configuration only model",
            configuration={"temperature": 0},
        ),
    )
    repeated = service.update_model(
        model["id"],
        ModelConfigurationUpdate(
            display_name="Updated configuration only model",
            configuration={"temperature": 0},
        ),
    )

    assert updated["enabled"] is False
    assert repeated["id"] == updated["id"]
    assert len(repository.models) == 1
    assert updated["available"] is False
    assert updated["default_effective"] is False
    assert updated["runtime_actions"]["enable"]["reason_code"] == (
        "provider_adapter_not_executable"
    )
    assert "No executable runtime adapter" in (
        updated["runtime_actions"]["enable"]["reason"] or ""
    )

    for operation in (
        lambda: service.set_model_enabled(model["id"], enabled=True),
        lambda: service.validate_model(model["id"]),
        lambda: service.set_default_model(model["id"], is_default=True),
    ):
        with pytest.raises(AIConfigurationError) as exc_info:
            operation()
        assert exc_info.value.status_code == 409
        assert exc_info.value.message


def test_default_selection_is_transactional_idempotent_and_referenced_models_conflict() -> None:
    service, repository = _service()
    provider = _available_provider(service, "default-provider")
    first = _available_model(service, provider["id"], "first-model")
    second = _available_model(service, provider["id"], "second-model")

    service.set_default_model(first["id"], is_default=True)
    service.set_default_model(second["id"], is_default=True)
    assert repository.models[first["id"]].is_default is False
    assert repository.models[second["id"]].is_default is True
    assert repository.default_lock_count == 2

    service.set_default_model(second["id"], is_default=True)
    assert repository.default_lock_count == 2

    repository.references.add(first["id"])
    with pytest.raises(AIConfigurationError) as exc_info:
        service.archive_model(first["id"])
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "model_has_runtime_references"


def test_read_only_actor_cannot_mutate_and_ai_permissions_are_organization_delegable() -> None:
    no_read_service, _repository = _service(
        permissions=frozenset({"ai.providers:administer"})
    )
    with pytest.raises(AIConfigurationError) as read_exc_info:
        no_read_service.workspace()
    assert read_exc_info.value.status_code == 403

    read_service, _repository = _service(
        permissions=frozenset({"ai.configuration:read"})
    )
    assert read_service.workspace()["capabilities"]["administer_providers"] is False
    with pytest.raises(AIConfigurationError) as exc_info:
        read_service.create_provider(_provider_payload("forbidden-provider"))
    assert exc_info.value.status_code == 403

    access_service = OrganizationAccessManagementService(
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        actor_reference="authenticated-user",
        actor_permissions=frozenset(
            {
                "ai.configuration:read",
                "ai.providers:administer",
                "platform.operations:administer",
            }
        ),
        correlation_id=None,
    )
    assert access_service._permission_is_delegable(  # noqa: SLF001
        Permission(resource="ai.providers", action="administer")
    )
    with pytest.raises(OrganizationAccessError, match="permission_not_delegable"):
        access_service._assert_permission_delegable(  # noqa: SLF001
            Permission(resource="platform.operations", action="administer")
        )


def test_api_policy_separates_read_administer_and_validation_permissions() -> None:
    assert required_permissions(
        "/api/platform/dashboard/capabilities",
        "GET",
    ) == frozenset(
        {"organization.dashboard:read", "ai.configuration:read"}
    )
    assert required_permissions("/api/ai/configuration", "GET") == frozenset(
        {"ai.configuration:read"}
    )
    assert required_permissions("/api/ai/providers", "GET") == frozenset(
        {"ai.configuration:read"}
    )
    assert required_permissions("/api/ai/providers", "POST") == frozenset(
        {"ai.configuration:administer", "ai.providers:administer"}
    )
    assert required_permissions(
        f"/api/ai/providers/{uuid.uuid4()}/validate",
        "POST",
    ) == frozenset({"ai.validation:execute"})
    assert required_permissions("/api/ai/models", "POST") == frozenset(
        {"ai.configuration:administer", "ai.models:administer"}
    )


def test_permission_catalog_and_migration_reconciliation_are_versioned_contracts() -> None:
    ai_permissions = [
        (resource, action)
        for resource, action, _description in REFERENCE_PERMISSIONS
        if resource.startswith("ai.")
    ]
    assert ai_permissions == [
        ("ai.configuration", "read"),
        ("ai.providers", "administer"),
        ("ai.models", "administer"),
        ("ai.validation", "execute"),
    ]
    assert len(ai_permissions) == len(set(ai_permissions))

    migration_990 = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260728_990_ai_provider_model_configuration.py"
    ).read_text(encoding="utf-8")
    migration_991 = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260728_991_reconcile_ai_role_permissions.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20260728_991"' in migration_991
    assert 'down_revision = "20260728_990"' in migration_991
    assert "ON CONFLICT (resource, action) DO UPDATE" in migration_990
    assert "INSERT INTO security.role_permissions" not in migration_990

    assert "INSERT INTO security.role_permissions" in migration_991
    assert "source_permission.resource = 'reference_tenant'" in migration_991
    assert "source_permission.action = 'administer'" in migration_991
    assert "role.organization_id IS NOT NULL" in migration_991
    assert "role.status = 'active'" in migration_991
    assert "role.is_system" in migration_991
    assert "role.config @> '{\"protected\": true}'::jsonb" in migration_991
    assert "role.config @> '{\"reference_tenant\": true}'::jsonb" in migration_991
    assert "role.config ->> 'managed_by' = 'platform'" in migration_991
    for resource, action in ai_permissions:
        assert f"('{resource}', '{action}')" in migration_991
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in migration_991
    assert "role.code" not in migration_991
    assert "organization_id =" not in migration_991
    assert "safe downgrade is intentionally non-destructive" in migration_991

    assert "reconcile_reference_tenant_permissions" in (
        Path(__file__).parents[1] / "app" / "services" / "reference_tenant.py"
    ).read_text(encoding="utf-8")
