from __future__ import annotations

from types import SimpleNamespace

from app.schemas.recovery import BackupArtifactCreate
from app.services.recovery_resource_identity import (
    IDENTITY_POSTGRESQL,
    LEGACY_POSTGRESQL,
    PLATFORM_POSTGRESQL,
)
from app.services.recovery_runtime import _backup_completion_blockers, _required_resource_types


def _policy(*, scope: str = "platform") -> SimpleNamespace:
    return SimpleNamespace(
        scope=scope,
        database_backup_enabled=True,
        object_storage_backup_enabled=False,
        configuration_backup_enabled=False,
        verification_required=True,
        evidence_max_age_hours=24,
    )


def _backup() -> SimpleNamespace:
    return SimpleNamespace(
        manifest_hash="manifest",
        database_included=True,
        object_storage_included=False,
        configuration_included=False,
        provider_execution_id="backup-provider-1",
        provider_type="external_evidence",
    )


def _artifact(resource_type: str, metadata: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        resource_type=resource_type,
        verification_status="verified",
        metadata_payload=metadata or {},
        provider_reference=None,
        checksum_algorithm=None,
        checksum=None,
    )


def test_backup_artifact_schema_accepts_authoritative_database_resource_types() -> None:
    for resource_type in (PLATFORM_POSTGRESQL, IDENTITY_POSTGRESQL, LEGACY_POSTGRESQL):
        payload = BackupArtifactCreate(artifact_type="database", resource_type=resource_type)
        assert payload.resource_type == resource_type


def test_platform_runtime_requires_both_database_authorities() -> None:
    required = _required_resource_types(_policy())
    assert PLATFORM_POSTGRESQL in required
    assert IDENTITY_POSTGRESQL in required
    assert LEGACY_POSTGRESQL not in required


def test_organization_runtime_requires_only_platform_database_authority() -> None:
    required = _required_resource_types(_policy(scope="organization"))
    assert PLATFORM_POSTGRESQL in required
    assert IDENTITY_POSTGRESQL not in required


def test_legacy_postgresql_artifact_does_not_satisfy_platform_backup_completion() -> None:
    artifacts = [
        _artifact(LEGACY_POSTGRESQL, {"postgresql_version": "16", "alembic_revision": "legacy"}),
        _artifact("migration_manifest", {"alembic_revision": "20260825_2200"}),
        _artifact("release_manifest", {"application_version": "1.5.0"}),
    ]

    blockers = _backup_completion_blockers(_policy(), _backup(), artifacts)

    assert "PLATFORM_POSTGRESQL_ARTIFACT_MISSING" in blockers
    assert "IDENTITY_POSTGRESQL_ARTIFACT_MISSING" in blockers


def test_both_database_authorities_satisfy_database_resource_requirements() -> None:
    artifacts = [
        _artifact(PLATFORM_POSTGRESQL, {"postgresql_version": "16", "alembic_revision": "20260825_2200"}),
        _artifact(IDENTITY_POSTGRESQL, {"postgresql_version": "16"}),
        _artifact("migration_manifest", {"alembic_revision": "20260825_2200"}),
        _artifact("release_manifest", {"application_version": "1.5.0"}),
    ]

    blockers = _backup_completion_blockers(_policy(), _backup(), artifacts)

    assert "PLATFORM_POSTGRESQL_ARTIFACT_MISSING" not in blockers
    assert "IDENTITY_POSTGRESQL_ARTIFACT_MISSING" not in blockers
    assert "PLATFORM_POSTGRESQL_VERSION_MISSING" not in blockers
    assert "IDENTITY_POSTGRESQL_VERSION_MISSING" not in blockers
