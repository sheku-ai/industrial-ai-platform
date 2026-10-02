from __future__ import annotations

import pytest

from app.services.recovery_resource_identity import (
    IDENTITY_POSTGRESQL,
    LEGACY_POSTGRESQL,
    PLATFORM_POSTGRESQL,
    is_database_authority,
    legacy_postgresql_satisfies_authority,
    missing_required_resources,
    normalize_resource_type,
    required_database_authorities,
)


def test_platform_recovery_requires_both_postgresql_authorities() -> None:
    assert required_database_authorities(database_backup_enabled=True, scope="platform") == (
        PLATFORM_POSTGRESQL,
        IDENTITY_POSTGRESQL,
    )


def test_organization_recovery_requires_platform_postgresql_only() -> None:
    assert required_database_authorities(database_backup_enabled=True, scope="organization") == (PLATFORM_POSTGRESQL,)


def test_legacy_postgresql_does_not_satisfy_authoritative_database_identity() -> None:
    assert normalize_resource_type(LEGACY_POSTGRESQL) == LEGACY_POSTGRESQL
    assert legacy_postgresql_satisfies_authority(LEGACY_POSTGRESQL) is False
    assert is_database_authority(LEGACY_POSTGRESQL) is False


def test_missing_required_resources_keeps_database_authorities_distinct() -> None:
    missing = missing_required_resources(
        (PLATFORM_POSTGRESQL, IDENTITY_POSTGRESQL),
        (PLATFORM_POSTGRESQL,),
    )
    assert missing == (IDENTITY_POSTGRESQL,)


def test_unknown_resource_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported_recovery_resource_type"):
        normalize_resource_type("customer_database")
