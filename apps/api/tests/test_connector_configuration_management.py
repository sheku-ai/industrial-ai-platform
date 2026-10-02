from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.models.audit import AuditEvent, AuditHistory
from app.models.connectors import Connector, ConnectorConfig, ConnectorType
from app.schemas.connector_configuration import (
    ConnectorConfigurationCreate,
    ConnectorConfigurationUpdate,
)
from app.secret_refs.base import SecretResolutionResult
from app.secret_refs.registry import SecretResolverRegistry
from app.services.connector_configuration import (
    ADMIN_PERMISSION,
    READ_PERMISSION,
    ConnectorConfigurationError,
    ConnectorConfigurationService,
    connector_type_contract,
)


class _ResolverThatMustNotExecute:
    resolver_type = "test-reference"

    def __init__(self) -> None:
        self.resolve_calls = 0

    def resolve(self, _reference) -> SecretResolutionResult:
        self.resolve_calls += 1
        raise AssertionError("connector configuration must not resolve credentials")


class _FakeRepository:
    def __init__(self, organization_id: uuid.UUID) -> None:
        self.organization_id = organization_id
        self.connector_types: dict[uuid.UUID, ConnectorType] = {}
        self.connectors: dict[uuid.UUID, Connector] = {}
        self.configurations: list[ConnectorConfig] = []
        self.audit: list[AuditEvent | AuditHistory] = []
        self.commit_count = 0

    def get_connector(self, connector_id, *, for_update=False):
        item = self.connectors.get(connector_id)
        return (
            item
            if item is not None and item.organization_id == self.organization_id
            else None
        )

    def get_connector_by_code(self, code):
        return next(
            (
                item
                for item in self.connectors.values()
                if item.organization_id == self.organization_id and item.code == code
            ),
            None,
        )

    def get_connector_type(self, connector_type_id):
        return self.connector_types.get(connector_type_id)

    def current_configuration(self, connector_id):
        rows = [
            item for item in self.configurations if item.connector_id == connector_id
        ]
        return max(
            rows,
            key=lambda item: (item.is_active, item.version, item.created_at),
            default=None,
        )

    def deactivate_configurations(self, connector_id):
        for item in self.configurations:
            if item.connector_id == connector_id:
                item.is_active = False

    def add(self, item):
        now = datetime.now(UTC)
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        if getattr(item, "created_at", None) is None:
            item.created_at = now
        if getattr(item, "updated_at", None) is None:
            item.updated_at = now
        if isinstance(item, Connector):
            self.connectors[item.id] = item
        elif isinstance(item, ConnectorConfig):
            if item not in self.configurations:
                self.configurations.append(item)
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


def _connector_type() -> ConnectorType:
    return ConnectorType(
        id=uuid.uuid4(),
        code="generic-source",
        name="Generic governed source",
        edition="community",
        connector_kind="document_source",
        description="Generic catalog-driven connector.",
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "endpoint": {
                    "type": "string",
                    "title": "Endpoint",
                    "format": "uri",
                },
                "region": {
                    "type": "string",
                    "title": "Region",
                    "enum": ["north", "south"],
                },
            },
            "required": ["endpoint"],
            "credential": {
                "supported": True,
                "required": True,
                "resolver_types": ["test-reference"],
            },
            "runtime_executable": False,
        },
        status="available",
    )


def _service(
    *,
    organization_id: uuid.UUID | None = None,
    permissions: frozenset[str] = frozenset({READ_PERMISSION, ADMIN_PERMISSION}),
) -> tuple[
    ConnectorConfigurationService,
    _FakeRepository,
    _ResolverThatMustNotExecute,
]:
    organization_id = organization_id or uuid.uuid4()
    resolver = _ResolverThatMustNotExecute()
    registry = SecretResolverRegistry()
    registry.register(resolver)
    service = ConnectorConfigurationService(
        None,  # type: ignore[arg-type]
        organization_id=organization_id,
        actor_reference="authenticated-user",
        actor_permissions=permissions,
        correlation_id="connector-correlation",
        secret_registry=registry,
    )
    repository = _FakeRepository(organization_id)
    service.repository = repository  # type: ignore[assignment]
    return service, repository, resolver


def _payload(connector_type_id: uuid.UUID, code: str = "governed-source"):
    return ConnectorConfigurationCreate(
        connector_type_id=connector_type_id,
        code=code,
        name="Governed source",
        configuration={
            "endpoint": "https://source.example",
            "region": "north",
        },
        credential={
            "resolver_type": "test-reference",
            "reference": "SOURCE_CREDENTIAL_REFERENCE",
        },
    )


def test_create_is_scoped_audited_secret_safe_and_does_not_execute_resolver() -> None:
    service, repository, resolver = _service()
    connector_type = _connector_type()
    repository.connector_types[connector_type.id] = connector_type

    result = service.create(_payload(connector_type.id))
    serialized = json.dumps(result, default=str)

    assert result["status"] == "disabled"
    assert result["enabled"] is False
    assert result["configuration_version"] == 1
    assert result["credential_configured"] is True
    assert "credential_reference" not in result
    assert "SOURCE_CREDENTIAL_REFERENCE" not in serialized
    assert resolver.resolve_calls == 0
    assert len(repository.audit) == 2
    assert all(item.organization_id == repository.organization_id for item in repository.audit)


def test_unknown_secret_and_foreign_configuration_are_rejected() -> None:
    service, repository, _resolver = _service()
    connector_type = _connector_type()
    repository.connector_types[connector_type.id] = connector_type

    with pytest.raises(
        ConnectorConfigurationError,
        match="connector_configuration_unknown_field",
    ):
        service.create(
            ConnectorConfigurationCreate(
                connector_type_id=connector_type.id,
                code="unsafe-source",
                name="Unsafe source",
                configuration={
                    "endpoint": "https://source.example",
                    "api_key": "must-not-enter-contract",
                },
                credential={
                    "resolver_type": "test-reference",
                    "reference": "SAFE_EXTERNAL_REFERENCE",
                },
            )
        )

    foreign = Connector(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        connector_type_id=connector_type.id,
        code="foreign",
        name="Foreign",
        config={},
        status="disabled",
    )
    repository.connectors[foreign.id] = foreign
    with pytest.raises(
        ConnectorConfigurationError,
        match="connector_configuration_not_found",
    ):
        service.get(foreign.id)


def test_update_versions_configuration_and_lifecycle_actions_are_idempotent() -> None:
    service, repository, resolver = _service()
    connector_type = _connector_type()
    repository.connector_types[connector_type.id] = connector_type
    created = service.create(_payload(connector_type.id))

    with pytest.raises(
        ConnectorConfigurationError,
        match="connector_configuration_version_conflict",
    ):
        service.update(
            created["id"],
            ConnectorConfigurationUpdate(
                expected_version=0,
                name="Stale update",
            ),
        )

    updated = service.update(
        created["id"],
        ConnectorConfigurationUpdate(
            expected_version=1,
            name="Updated source",
            configuration={
                "endpoint": "https://updated.example",
                "region": "south",
            },
        ),
    )
    assert updated["configuration_version"] == 2
    assert updated["credential_configured"] is True

    enabled = service.set_enabled(
        created["id"],
        enabled=True,
        expected_version=2,
    )
    assert enabled["enabled"] is True
    assert service.set_enabled(
        created["id"],
        enabled=True,
        expected_version=2,
    )["enabled"] is True

    archived = service.archive(created["id"], expected_version=2)
    assert archived["lifecycle_status"] == "archived"
    assert service.archive(
        created["id"],
        expected_version=2,
    )["lifecycle_status"] == "archived"
    restored = service.restore(created["id"], expected_version=2)
    assert restored["lifecycle_status"] == "active"
    assert restored["enabled"] is False
    assert resolver.resolve_calls == 0


def test_catalog_contract_blocks_required_sensitive_metadata() -> None:
    connector_type = _connector_type()
    connector_type.config_schema = {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "sensitive": True,
            }
        },
        "required": ["password"],
    }

    contract = connector_type_contract(
        connector_type,
        resolver_types=("test-reference",),
    )

    assert contract["configurable"] is False
    assert contract["configuration_fields"] == []
    assert (
        contract["configuration_unavailable_reason"]
        == "connector_configuration_requires_sensitive_field"
    )


def test_mutation_requires_existing_connector_administer_permission() -> None:
    service, repository, _resolver = _service(
        permissions=frozenset({READ_PERMISSION}),
    )
    connector_type = _connector_type()
    repository.connector_types[connector_type.id] = connector_type

    with pytest.raises(
        ConnectorConfigurationError,
        match="connector_configuration_permission_required",
    ):
        service.create(_payload(connector_type.id))
