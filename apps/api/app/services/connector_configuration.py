from __future__ import annotations

import re
import uuid
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.connectors import Connector, ConnectorConfig, ConnectorType
from app.repositories.connector_configuration import ConnectorConfigurationRepository
from app.schemas.connector_configuration import (
    ConnectorConfigurationCreate,
    ConnectorConfigurationUpdate,
    ConnectorCredentialReferenceInput,
)
from app.secret_refs.environment import EnvironmentSecretResolver
from app.secret_refs.registry import SecretResolverRegistry

READ_PERMISSION = "reference_tenant:read"
ADMIN_PERMISSION = "reference_tenant:administer"
UNUSABLE_TYPE_STATUSES = frozenset({"archived", "deleted", "disabled", "failed"})
ENABLED_CONNECTOR_STATUSES = frozenset({"active", "available", "enabled"})
SENSITIVE_FRAGMENTS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
SUPPORTED_FIELD_TYPES = frozenset({"boolean", "integer", "number", "string"})
FIELD_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")


class ConnectorConfigurationError(Exception):
    def __init__(self, status_code: int, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message or code.replace("_", " ").capitalize() + "."


@lru_cache
def get_connector_secret_registry() -> SecretResolverRegistry:
    registry = SecretResolverRegistry()
    registry.register(EnvironmentSecretResolver())
    return registry


def connector_type_is_usable(connector_type: ConnectorType) -> bool:
    return (
        connector_type.code.strip().casefold() != "disabled"
        and connector_type.status.strip().casefold() not in UNUSABLE_TYPE_STATUSES
    )


def connector_is_enabled(status: str | None) -> bool:
    return str(status or "").strip().casefold() in ENABLED_CONNECTOR_STATUSES


def _is_sensitive_key(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS)


def _schema_properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return None
    result: dict[str, dict[str, Any]] = {}
    for key, definition in properties.items():
        if isinstance(key, str) and isinstance(definition, dict):
            result[key] = definition
        else:
            return None
    return result


def _field_type(definition: dict[str, Any]) -> str:
    raw_type = definition.get("type", "string")
    if isinstance(raw_type, list):
        candidates = [str(item) for item in raw_type if item != "null"]
        return candidates[0] if len(candidates) == 1 else "unsupported"
    return str(raw_type).strip().casefold()


def _credential_contract(
    schema: dict[str, Any],
    resolver_types: tuple[str, ...],
) -> dict[str, Any]:
    raw = schema.get("credential")
    metadata = raw if isinstance(raw, dict) else {}
    supported = (
        isinstance(raw, dict) and metadata.get("supported", True) is not False
    ) or schema.get("credential_required") is True
    required = bool(metadata.get("required", schema.get("credential_required", False)))
    declared_resolvers = metadata.get("resolver_types")
    if isinstance(declared_resolvers, list):
        declared = {
            str(item).strip()
            for item in declared_resolvers
            if isinstance(item, str) and item.strip()
        }
        available = [item for item in resolver_types if item in declared]
    else:
        available = list(resolver_types) if supported else []
    effective_supported = supported and bool(available)
    return {
        "supported": effective_supported,
        "required": required,
        "resolver_types": available,
    }


def connector_type_contract(
    connector_type: ConnectorType,
    *,
    resolver_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema = connector_type.config_schema if isinstance(connector_type.config_schema, dict) else {}
    properties = _schema_properties(schema)
    required_values = schema.get("required", [])
    required = (
        {str(item) for item in required_values if isinstance(item, str)}
        if isinstance(required_values, list)
        else set()
    )
    fields: list[dict[str, Any]] = []
    blocking_reason: str | None = None

    if properties is None:
        blocking_reason = "connector_configuration_schema_invalid"
        properties = {}

    for key, definition in properties.items():
        field_type = _field_type(definition)
        sensitive = (
            _is_sensitive_key(key)
            or definition.get("sensitive") is True
            or str(definition.get("format", "")).casefold() in {"password", "secret"}
        )
        field_required = key in required
        editable = (
            definition.get("readOnly") is not True
            and definition.get("editable", True) is not False
        )
        supported = (
            FIELD_KEY_PATTERN.fullmatch(key) is not None
            and field_type in SUPPORTED_FIELD_TYPES
            and not sensitive
        )
        if field_required and (not supported or not editable):
            blocking_reason = (
                "connector_configuration_requires_sensitive_field"
                if sensitive
                else "connector_configuration_schema_unsupported"
            )
        if not supported:
            continue
        enum_values = definition.get("enum")
        options = (
            [
                value
                for value in enum_values
                if isinstance(value, str | int | float | bool)
            ]
            if isinstance(enum_values, list)
            else []
        )
        fields.append(
            {
                "key": key,
                "label": str(definition.get("title") or key.replace("_", " ")),
                "description": (
                    str(definition["description"])
                    if definition.get("description")
                    else None
                ),
                "type": field_type,
                "required": field_required,
                "editable": editable,
                "options": options,
            }
        )

    credential = _credential_contract(schema, resolver_types)
    if credential["required"] and (
        not credential["supported"] or not credential["resolver_types"]
    ):
        blocking_reason = "connector_credential_resolver_unavailable"

    configurable = (
        connector_type_is_usable(connector_type)
        and schema.get("configurable", schema.get("configuration_supported", True)) is not False
        and blocking_reason is None
    )
    runtime_capabilities = schema.get("runtime_capabilities") or schema.get("capabilities") or []
    runtime_executable = bool(
        schema.get("runtime_executable") is True
        or schema.get("executable") is True
        or (
            isinstance(runtime_capabilities, list)
            and any(
                isinstance(item, dict) and item.get("executable") is True
                for item in runtime_capabilities
            )
        )
    )
    return {
        "configurable": configurable,
        "configuration_unavailable_reason": blocking_reason,
        "configuration_fields": fields,
        "credential": credential,
        "runtime_executable": runtime_executable,
    }


def _validate_scalar(
    key: str,
    value: Any,
    definition: dict[str, Any],
) -> Any:
    field_type = _field_type(definition)
    if field_type == "string":
        if not isinstance(value, str):
            raise ConnectorConfigurationError(422, "connector_configuration_field_type")
        normalized: Any = value.strip()
        minimum = definition.get("minLength")
        maximum = definition.get("maxLength")
        if isinstance(minimum, int) and len(normalized) < minimum:
            raise ConnectorConfigurationError(422, "connector_configuration_field_too_short")
        if isinstance(maximum, int) and len(normalized) > maximum:
            raise ConnectorConfigurationError(422, "connector_configuration_field_too_long")
        pattern = definition.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.fullmatch(pattern, normalized) is not None
            except re.error as exc:
                raise ConnectorConfigurationError(
                    409,
                    "connector_configuration_schema_invalid",
                ) from exc
            if not matches:
                raise ConnectorConfigurationError(422, "connector_configuration_field_pattern")
        if str(definition.get("format", "")).casefold() in {"uri", "url"} and normalized:
            parsed = urlsplit(normalized)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ConnectorConfigurationError(422, "connector_configuration_url_invalid")
    elif field_type == "boolean":
        if not isinstance(value, bool):
            raise ConnectorConfigurationError(422, "connector_configuration_field_type")
        normalized = value
    elif field_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConnectorConfigurationError(422, "connector_configuration_field_type")
        normalized = value
    elif field_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ConnectorConfigurationError(422, "connector_configuration_field_type")
        normalized = value
    else:
        raise ConnectorConfigurationError(409, "connector_configuration_schema_unsupported")

    enum_values = definition.get("enum")
    if isinstance(enum_values, list) and normalized not in enum_values:
        raise ConnectorConfigurationError(422, "connector_configuration_field_not_allowed")
    if isinstance(normalized, int | float) and not isinstance(normalized, bool):
        minimum = definition.get("minimum")
        maximum = definition.get("maximum")
        if isinstance(minimum, int | float) and normalized < minimum:
            raise ConnectorConfigurationError(422, "connector_configuration_field_too_small")
        if isinstance(maximum, int | float) and normalized > maximum:
            raise ConnectorConfigurationError(422, "connector_configuration_field_too_large")
    return normalized


def validate_connector_configuration(
    connector_type: ConnectorType,
    configuration: dict[str, Any],
    *,
    resolver_types: tuple[str, ...],
    allow_read_only: bool = False,
) -> dict[str, Any]:
    contract = connector_type_contract(connector_type, resolver_types=resolver_types)
    if not contract["configurable"]:
        raise ConnectorConfigurationError(
            409,
            str(contract["configuration_unavailable_reason"] or "connector_type_not_configurable"),
        )
    schema = connector_type.config_schema if isinstance(connector_type.config_schema, dict) else {}
    properties = _schema_properties(schema)
    if properties is None:
        raise ConnectorConfigurationError(409, "connector_configuration_schema_invalid")
    required_values = schema.get("required", [])
    required = (
        {str(item) for item in required_values if isinstance(item, str)}
        if isinstance(required_values, list)
        else set()
    )
    unknown = set(configuration) - set(properties)
    if unknown:
        raise ConnectorConfigurationError(422, "connector_configuration_unknown_field")
    missing = required - set(configuration)
    if missing:
        raise ConnectorConfigurationError(422, "connector_configuration_required_field")

    validated: dict[str, Any] = {}
    for key, value in configuration.items():
        definition = properties[key]
        if (
            _is_sensitive_key(key)
            or definition.get("sensitive") is True
            or str(definition.get("format", "")).casefold() in {"password", "secret"}
        ):
            raise ConnectorConfigurationError(422, "connector_configuration_secret_field")
        if (
            not allow_read_only
            and (
                definition.get("readOnly") is True
                or definition.get("editable", True) is False
            )
        ):
            raise ConnectorConfigurationError(422, "connector_configuration_field_read_only")
        validated[key] = _validate_scalar(key, value, definition)
    return validated


class ConnectorConfigurationService:
    def __init__(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID,
        actor_reference: str,
        actor_permissions: frozenset[str],
        correlation_id: str | None,
        secret_registry: SecretResolverRegistry | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.actor_reference = actor_reference
        self.actor_permissions = actor_permissions
        self.correlation_id = correlation_id
        self.repository = ConnectorConfigurationRepository(db, organization_id)
        self.secret_registry = secret_registry or get_connector_secret_registry()

    @property
    def resolver_types(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in self.secret_registry.registered_types()
            if value != "disabled"
        )

    def get(self, connector_id: uuid.UUID) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        return self._read(self._connector(connector_id))

    def create(self, payload: ConnectorConfigurationCreate) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        connector_type = self._connector_type(payload.connector_type_id)
        contract = self._require_configurable_type(connector_type)
        if self.repository.get_connector_by_code(payload.code) is not None:
            raise ConnectorConfigurationError(409, "connector_code_conflict")
        configuration = validate_connector_configuration(
            connector_type,
            payload.configuration,
            resolver_types=self.resolver_types,
        )
        credential = self._validated_credential(payload.credential, contract)
        if contract["credential"]["required"] and credential is None:
            raise ConnectorConfigurationError(422, "connector_credential_reference_required")

        item = Connector(
            organization_id=self.organization_id,
            connector_type_id=connector_type.id,
            code=payload.code,
            name=payload.name,
            config={},
            status="disabled",
            credential_resolver_type=credential.resolver_type if credential else None,
            credential_reference=credential.reference if credential else None,
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.repository.add(item)
        self.repository.flush()
        configuration_row = ConnectorConfig(
            connector_id=item.id,
            version=1,
            config=configuration,
            is_active=True,
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.repository.add(configuration_row)
        self._audit(
            item,
            "created",
            after=self._safe_state(item, configuration_row),
        )
        self._commit(item)
        return self._read(item)

    def update(
        self,
        connector_id: uuid.UUID,
        payload: ConnectorConfigurationUpdate,
    ) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        item = self._connector(connector_id, for_update=True)
        self._require_not_archived(item)
        connector_type = self._connector_type(item.connector_type_id)
        contract = self._require_configurable_type(connector_type)
        current = self.repository.current_configuration(item.id)
        self._require_version(payload.expected_version, current)
        before = self._safe_state(item, current)
        changed = payload.model_dump(exclude_unset=True)

        if "name" in changed:
            item.name = payload.name or item.name

        next_configuration = current
        if payload.configuration is not None:
            validated = validate_connector_configuration(
                connector_type,
                payload.configuration,
                resolver_types=self.resolver_types,
            )
            try:
                existing = self._validated_existing_configuration(connector_type, current)
            except ConnectorConfigurationError:
                existing = {}
            properties = _schema_properties(connector_type.config_schema or {}) or {}
            protected_values = {
                key: value
                for key, value in existing.items()
                if key in properties
                and (
                    properties[key].get("readOnly") is True
                    or properties[key].get("editable", True) is False
                )
            }
            validated = validate_connector_configuration(
                connector_type,
                {**protected_values, **validated},
                resolver_types=self.resolver_types,
                allow_read_only=True,
            )
            next_version = (current.version if current else 0) + 1
            self.repository.deactivate_configurations(item.id)
            next_configuration = ConnectorConfig(
                connector_id=item.id,
                version=next_version,
                config=validated,
                is_active=True,
                created_by=self.actor_reference,
                updated_by=self.actor_reference,
            )
            self.repository.add(next_configuration)

        if payload.credential is not None:
            credential = self._validated_credential(payload.credential, contract)
            item.credential_resolver_type = credential.resolver_type
            item.credential_reference = credential.reference
        elif payload.clear_credential:
            if contract["credential"]["required"]:
                raise ConnectorConfigurationError(422, "connector_credential_reference_required")
            item.credential_resolver_type = None
            item.credential_reference = None

        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            item,
            "updated",
            before=before,
            after=self._safe_state(item, next_configuration),
        )
        self._commit(item)
        return self._read(item)

    def set_enabled(
        self,
        connector_id: uuid.UUID,
        *,
        enabled: bool,
        expected_version: int,
    ) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        item = self._connector(connector_id, for_update=True)
        self._require_not_archived(item)
        connector_type = self._connector_type(item.connector_type_id)
        contract = self._require_configurable_type(connector_type)
        current = self.repository.current_configuration(item.id)
        self._require_version(expected_version, current)
        if enabled:
            self._validated_existing_configuration(connector_type, current)
            if contract["credential"]["required"] and not item.credential_reference:
                raise ConnectorConfigurationError(409, "connector_credential_reference_required")
        target_status = "enabled" if enabled else "disabled"
        if item.status == target_status:
            return self._read(item)
        before = self._safe_state(item, current)
        item.status = target_status
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            item,
            "enabled" if enabled else "disabled",
            before=before,
            after=self._safe_state(item, current),
        )
        self._commit(item)
        return self._read(item)

    def archive(self, connector_id: uuid.UUID, *, expected_version: int) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        item = self._connector(connector_id, for_update=True)
        current = self.repository.current_configuration(item.id)
        self._require_version(expected_version, current)
        if item.status == "archived":
            return self._read(item)
        before = self._safe_state(item, current)
        item.status = "archived"
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            item,
            "archived",
            before=before,
            after=self._safe_state(item, current),
        )
        self._commit(item)
        return self._read(item)

    def restore(self, connector_id: uuid.UUID, *, expected_version: int) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        item = self._connector(connector_id, for_update=True)
        current = self.repository.current_configuration(item.id)
        self._require_version(expected_version, current)
        if item.status != "archived":
            return self._read(item)
        connector_type = self._connector_type(item.connector_type_id)
        self._require_configurable_type(connector_type)
        before = self._safe_state(item, current)
        item.status = "disabled"
        item.updated_by = self.actor_reference
        self.repository.add(item)
        self._audit(
            item,
            "restored",
            before=before,
            after=self._safe_state(item, current),
        )
        self._commit(item)
        return self._read(item)

    def _connector(
        self,
        connector_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Connector:
        item = self.repository.get_connector(connector_id, for_update=for_update)
        if item is None:
            raise ConnectorConfigurationError(404, "connector_configuration_not_found")
        return item

    def _connector_type(self, connector_type_id: uuid.UUID) -> ConnectorType:
        item = self.repository.get_connector_type(connector_type_id)
        if item is None:
            raise ConnectorConfigurationError(404, "connector_type_not_found")
        return item

    def _require_configurable_type(self, connector_type: ConnectorType) -> dict[str, Any]:
        contract = connector_type_contract(
            connector_type,
            resolver_types=self.resolver_types,
        )
        if not contract["configurable"]:
            raise ConnectorConfigurationError(
                409,
                str(contract["configuration_unavailable_reason"] or "connector_type_not_configurable"),
            )
        return contract

    def _validated_credential(
        self,
        credential: ConnectorCredentialReferenceInput | None,
        contract: dict[str, Any],
    ) -> ConnectorCredentialReferenceInput | None:
        if credential is None:
            return None
        credential_contract = contract["credential"]
        if not credential_contract["supported"]:
            raise ConnectorConfigurationError(422, "connector_credential_not_supported")
        if credential.resolver_type not in credential_contract["resolver_types"]:
            raise ConnectorConfigurationError(422, "connector_credential_resolver_unsupported")
        if credential.resolver_type not in self.resolver_types:
            raise ConnectorConfigurationError(422, "connector_credential_resolver_unsupported")
        return credential

    def _validated_existing_configuration(
        self,
        connector_type: ConnectorType,
        configuration: ConnectorConfig | None,
    ) -> dict[str, Any]:
        return validate_connector_configuration(
            connector_type,
            configuration.config if configuration else {},
            resolver_types=self.resolver_types,
            allow_read_only=True,
        )

    def _require_version(
        self,
        expected_version: int,
        configuration: ConnectorConfig | None,
    ) -> None:
        current_version = configuration.version if configuration else 0
        if expected_version != current_version:
            raise ConnectorConfigurationError(409, "connector_configuration_version_conflict")

    def _require_not_archived(self, item: Connector) -> None:
        if item.status == "archived":
            raise ConnectorConfigurationError(409, "connector_configuration_archived")

    def _read(self, item: Connector) -> dict[str, Any]:
        connector_type = self._connector_type(item.connector_type_id)
        current = self.repository.current_configuration(item.id)
        try:
            configuration = self._validated_existing_configuration(connector_type, current)
            configuration_status = "valid"
        except ConnectorConfigurationError:
            configuration = {}
            configuration_status = "legacy_requires_review"
        return {
            "id": item.id,
            "connector_type_id": item.connector_type_id,
            "code": item.code,
            "name": item.name,
            "status": item.status,
            "enabled": connector_is_enabled(item.status),
            "lifecycle_status": "archived" if item.status == "archived" else "active",
            "configuration_version": current.version if current else 0,
            "configuration": configuration,
            "configuration_status": configuration_status,
            "credential_configured": bool(item.credential_reference),
            "credential_resolver_type": (
                item.credential_resolver_type if item.credential_reference else None
            ),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "created_by": item.created_by,
            "updated_by": item.updated_by,
        }

    def _safe_state(
        self,
        item: Connector,
        configuration: ConnectorConfig | None,
    ) -> dict[str, Any]:
        return {
            "connector_type_id": str(item.connector_type_id),
            "code": item.code,
            "name": item.name,
            "status": item.status,
            "configuration_version": configuration.version if configuration else 0,
            "configuration_keys": sorted(
                str(key) for key in (configuration.config if configuration else {})
            ),
            "credential_configured": bool(item.credential_reference),
            "credential_resolver_type": (
                item.credential_resolver_type if item.credential_reference else None
            ),
            "secrets_exposed": False,
        }

    def _audit(
        self,
        item: Connector,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self.repository.add(
            AuditEvent(
                organization_id=self.organization_id,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type="connector.configuration",
                resource_id=str(item.id),
                summary=action,
                metadata_json={
                    "action": action,
                    "correlation_id": self.correlation_id,
                    "postgresql_source_of_truth": True,
                    "provider_call_performed": False,
                    "secrets_exposed": False,
                },
            )
        )
        self.repository.add(
            AuditHistory(
                organization_id=self.organization_id,
                entity_type="connector.configuration",
                entity_id=str(item.id),
                action=action,
                before_state=before or {},
                after_state=after or {},
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _require(self, permission: str) -> None:
        if permission not in self.actor_permissions:
            raise ConnectorConfigurationError(403, "connector_configuration_permission_required")

    def _commit(self, item: object) -> None:
        try:
            self.repository.commit()
            self.repository.refresh(item)
        except IntegrityError as exc:
            self.repository.rollback()
            raise ConnectorConfigurationError(409, "connector_configuration_conflict") from exc
