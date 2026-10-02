from __future__ import annotations

from collections.abc import Iterable

PLATFORM_POSTGRESQL = "platform_postgresql"
IDENTITY_POSTGRESQL = "identity_postgresql"
LEGACY_POSTGRESQL = "postgresql"
OBJECT_STORAGE = "object_storage"
APPLICATION_CONFIGURATION = "application_configuration"
MIGRATION_MANIFEST = "migration_manifest"
RELEASE_MANIFEST = "release_manifest"
OTHER = "other"

CANONICAL_RESOURCE_TYPES = (
    PLATFORM_POSTGRESQL,
    IDENTITY_POSTGRESQL,
    OBJECT_STORAGE,
    APPLICATION_CONFIGURATION,
    MIGRATION_MANIFEST,
    RELEASE_MANIFEST,
    OTHER,
)

DATABASE_AUTHORITIES = (
    PLATFORM_POSTGRESQL,
    IDENTITY_POSTGRESQL,
)

ACCEPTED_RESOURCE_TYPES = (*CANONICAL_RESOURCE_TYPES, LEGACY_POSTGRESQL)


def is_database_authority(resource_type: str) -> bool:
    return resource_type in DATABASE_AUTHORITIES


def is_canonical_resource_type(resource_type: str) -> bool:
    return resource_type in CANONICAL_RESOURCE_TYPES


def normalize_resource_type(resource_type: str) -> str:
    normalized = resource_type.strip().lower()
    if normalized not in ACCEPTED_RESOURCE_TYPES:
        raise ValueError("unsupported_recovery_resource_type")
    return normalized


def required_database_authorities(*, database_backup_enabled: bool, scope: str) -> tuple[str, ...]:
    if not database_backup_enabled:
        return ()
    if scope == "platform":
        return DATABASE_AUTHORITIES
    if scope == "organization":
        return (PLATFORM_POSTGRESQL,)
    raise ValueError("unsupported_recovery_scope")


def missing_required_resources(required: Iterable[str], observed: Iterable[str]) -> tuple[str, ...]:
    observed_set = set(observed)
    return tuple(resource_type for resource_type in required if resource_type not in observed_set)


def legacy_postgresql_satisfies_authority(resource_type: str) -> bool:
    """Legacy generic PostgreSQL evidence is never authoritative for RC readiness."""
    return False
