from __future__ import annotations

import uuid
from datetime import UTC, datetime

import apps.api.scripts.smoke_recovery_readiness_e2e as recovery_smoke
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.recovery import BackupExecution, RecoveryPolicy, RestoreExecution
from app.services import recovery_runtime
from app.services.recovery_runtime import (
    _backup_completion_blockers,
    _required_resource_types,
    activate_recovery_policy,
    mask_storage_location,
)


class Artifact:
    def __init__(
        self,
        resource_type: str,
        verification_status: str = "verified",
        metadata_payload: dict[str, str] | None = None,
    ) -> None:
        self.resource_type = resource_type
        self.verification_status = verification_status
        self.metadata_payload = metadata_payload or {}


def _artifacts(*, database_status: str = "verified") -> list[Artifact]:
    return [
        Artifact(
            "platform_postgresql",
            database_status,
            {"postgresql_version": "16", "alembic_revision": "current-head"},
        ),
        Artifact(
            "identity_postgresql",
            database_status,
            {"postgresql_version": "16"},
        ),
        Artifact("object_storage", metadata_payload={"provider": "external_evidence"}),
        Artifact("application_configuration", metadata_payload={"format": "governed_configuration"}),
        Artifact("migration_manifest", metadata_payload={"alembic_revision": "current-head"}),
        Artifact("release_manifest", metadata_payload={"application_version": "test-version"}),
    ]


def _policy() -> RecoveryPolicy:
    policy = RecoveryPolicy(
        scope="platform",
        name="Policy",
        status="active",
        database_backup_enabled=True,
        object_storage_backup_enabled=True,
        configuration_backup_enabled=True,
        verification_required=True,
        evidence_max_age_hours=24,
        provider_type="external_evidence",
        provider_reference="external-evidence-provider",
    )
    return policy


def _activation_policy(status: str = "draft", organization_id: uuid.UUID | None = None) -> RecoveryPolicy:
    now = datetime.now(UTC)
    return RecoveryPolicy(
        id=uuid.uuid4(),
        organization_id=organization_id,
        scope="organization" if organization_id else "platform",
        name="Policy",
        description=None,
        status=status,
        database_backup_enabled=True,
        object_storage_backup_enabled=True,
        configuration_backup_enabled=True,
        backup_frequency="daily",
        retention_days=30,
        retention_count=7,
        rpo_minutes=60,
        rto_minutes=240,
        verification_required=True,
        restore_test_frequency="monthly",
        evidence_max_age_hours=168,
        provider_type="external_evidence",
        provider_reference=None,
        configuration_payload={},
        created_by="unit-test",
        activated_at=now if status == "active" else None,
        deactivated_at=None,
        created_at=now,
        updated_at=now,
    )


class FakeActivationRepository:
    def __init__(self, db) -> None:
        self.db = db

    def policies_for_activation(self, *, scope, organization_id, policy_id):
        return self.db.locked_policies


class FakeActivationSession:
    def __init__(self, locked_policies, fail_on_flush: int | None = None) -> None:
        self.locked_policies = locked_policies
        self.flush_count = 0
        self.rollback_count = 0
        self.fail_on_flush = fail_on_flush

    def add(self, value) -> None:
        return None

    def flush(self) -> None:
        self.flush_count += 1
        if self.fail_on_flush == self.flush_count:
            raise IntegrityError("update", {}, Exception("unique violation"))

    def rollback(self) -> None:
        self.rollback_count += 1


@pytest.fixture(autouse=True)
def fake_activation_repository(monkeypatch):
    monkeypatch.setattr(recovery_runtime, "RecoveryRepository", FakeActivationRepository)


def _backup() -> BackupExecution:
    backup = BackupExecution(
        scope="platform",
        policy_id="00000000-0000-0000-0000-000000000000",
        provider_type="external_evidence",
        idempotency_key="backup",
        status="running",
        backup_type="external",
        database_included=True,
        object_storage_included=True,
        configuration_included=True,
        consistent_snapshot=True,
        manifest_hash="manifest",
        input_hash="a" * 64,
    )
    return backup


def test_required_resource_types_include_database_object_storage_and_configuration() -> None:
    assert _required_resource_types(_policy()) == {
        "platform_postgresql",
        "identity_postgresql",
        "object_storage",
        "application_configuration",
    }


def test_activate_first_platform_policy() -> None:
    target = _activation_policy("draft")
    db = FakeActivationSession([target])

    result = activate_recovery_policy(db, target)

    assert result.id == target.id
    assert target.status == "active"
    assert target.activated_at is not None
    assert db.flush_count == 2


def test_activate_second_platform_policy_deactivates_first() -> None:
    old = _activation_policy("active")
    target = _activation_policy("draft")
    db = FakeActivationSession([old, target])

    result = activate_recovery_policy(db, target)

    assert result.id == target.id
    assert old.status == "inactive"
    assert old.deactivated_at is not None
    assert target.status == "active"
    assert target.activated_at is not None


def test_activate_same_policy_is_idempotent() -> None:
    target = _activation_policy("active")
    previous_activated_at = target.activated_at
    db = FakeActivationSession([target])

    result = activate_recovery_policy(db, target)

    assert result.id == target.id
    assert target.status == "active"
    assert target.activated_at == previous_activated_at
    assert db.flush_count == 0


def test_organization_policy_does_not_deactivate_another_organization_policy() -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    other_org_active = _activation_policy("active", organization_id=org_b)
    target = _activation_policy("draft", organization_id=org_a)
    db = FakeActivationSession([target])

    activate_recovery_policy(db, target)

    assert target.status == "active"
    assert other_org_active.status == "active"


def test_platform_policy_does_not_affect_organization_policy() -> None:
    org_policy = _activation_policy("active", organization_id=uuid.uuid4())
    target = _activation_policy("draft")
    db = FakeActivationSession([target])

    activate_recovery_policy(db, target)

    assert target.status == "active"
    assert org_policy.status == "active"


def test_concurrent_activation_returns_controlled_conflict() -> None:
    old = _activation_policy("active")
    target = _activation_policy("draft")
    db = FakeActivationSession([old, target], fail_on_flush=2)

    with pytest.raises(ValueError, match="recovery_policy_activation_conflict"):
        activate_recovery_policy(db, target)

    assert db.rollback_count == 1


def test_unique_constraint_remains_enforced_by_activation_contract() -> None:
    old = _activation_policy("active")
    target = _activation_policy("draft")
    db = FakeActivationSession([old, target])

    activate_recovery_policy(db, target)

    active = [policy for policy in (old, target) if policy.status == "active"]
    assert active == [target]


def test_smoke_stops_after_activation_failure(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_call(method, path, payload=None):
        calls.append((method, path))
        if path == "/platform/recovery/policies":
            return True, {"id": "policy-1", "status": "draft"}
        if path == "/platform/recovery/policies/policy-1/activate":
            return False, {"status": 409, "error": "recovery_policy_activation_conflict"}
        return True, {}

    monkeypatch.setattr(recovery_smoke, "_call", fake_call)

    assert recovery_smoke.main() == 1
    assert ("POST", "/platform/recovery/backups") not in calls
    assert not any(path == "/platform/recovery/readiness?scope=platform" for _, path in calls)


def test_smoke_rejects_stale_readiness_evidence(monkeypatch) -> None:
    def fake_call(method, path, payload=None):
        if path == "/platform/recovery/policies":
            return True, {"id": "policy-1", "status": "draft"}
        if path == "/platform/recovery/policies/policy-1/activate":
            return True, {"id": "policy-1", "status": "active"}
        if path == "/platform/recovery/backups":
            return True, {"id": "backup-1", "policy_id": "policy-1"}
        if path.endswith("/artifacts"):
            return True, {"id": "artifact-1"}
        if path == "/platform/recovery/backups/backup-1/complete":
            return True, {"id": "backup-1", "status": "completed"}
        if path == "/platform/recovery/restores":
            return True, {"id": "restore-1", "policy_id": "policy-1", "backup_execution_id": "backup-1"}
        if path == "/platform/recovery/restores/restore-1/complete":
            return True, {"id": "restore-1", "status": "completed"}
        if path == "/platform/recovery/restores/restore-1/verifications":
            return True, {"id": "verification-1", "restore_execution_id": "restore-1"}
        if path == "/platform/recovery/verifications/verification-1/complete":
            return True, {"id": "verification-1", "status": "passed"}
        if path == "/platform/recovery/readiness?scope=platform":
            return True, {
                "status": "passed",
                "active_policy": {"id": "stale-policy"},
                "latest_backup": {"id": "backup-1", "policy_id": "policy-1"},
                "latest_restore": {"id": "restore-1", "backup_execution_id": "backup-1"},
                "latest_restore_verification": {"id": "verification-1", "restore_execution_id": "restore-1"},
            }
        return True, {}

    monkeypatch.setattr(recovery_smoke, "_call", fake_call)

    assert recovery_smoke.main() == 1


def test_backup_completion_requires_database_artifact() -> None:
    artifacts = [artifact for artifact in _artifacts() if artifact.resource_type != "identity_postgresql"]
    blockers = _backup_completion_blockers(
        _policy(),
        _backup(),
        artifacts,
    )

    assert set(blockers) == {
        "IDENTITY_POSTGRESQL_ARTIFACT_MISSING",
        "IDENTITY_POSTGRESQL_VERSION_MISSING",
    }


def test_backup_completion_requires_object_storage_artifact() -> None:
    artifacts = [artifact for artifact in _artifacts() if artifact.resource_type != "object_storage"]
    blockers = _backup_completion_blockers(
        _policy(),
        _backup(),
        artifacts,
    )

    assert blockers == ["OBJECT_STORAGE_ARTIFACT_MISSING"]


def test_backup_completion_requires_verified_artifacts() -> None:
    blockers = _backup_completion_blockers(
        _policy(),
        _backup(),
        _artifacts(database_status="pending"),
    )

    assert set(blockers) == {
        "PLATFORM_POSTGRESQL_ARTIFACT_NOT_VERIFIED",
        "IDENTITY_POSTGRESQL_ARTIFACT_NOT_VERIFIED",
    }


def test_backup_completion_passes_with_complete_verified_evidence() -> None:
    blockers = _backup_completion_blockers(
        _policy(),
        _backup(),
        _artifacts(),
    )

    assert blockers == []


def test_restore_existing_environment_is_destructive_contract() -> None:
    restore = RestoreExecution(
        scope="platform",
        policy_id="00000000-0000-0000-0000-000000000000",
        backup_execution_id="00000000-0000-0000-0000-000000000000",
        provider_type="external_evidence",
        idempotency_key="restore",
        restore_target_type="existing_environment",
        destructive_operation=True,
        input_hash="b" * 64,
    )

    assert restore.destructive_operation is True


def test_secret_masking_does_not_expose_credentials() -> None:
    masked = mask_storage_location("s3://user:password@example-bucket/path")

    assert "password" not in masked
    assert "********" in masked
