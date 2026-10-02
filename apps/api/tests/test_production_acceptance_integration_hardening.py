from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.portal_acceptance import PORTAL_VALIDATION_TYPES
from app.schemas.portal_acceptance import PortalAcceptanceEvidenceCreate
from app.services.operational_observability_runtime import current_critical_operational_signals
from app.services.portal_acceptance_runtime import (
    build_portal_acceptance_readiness,
    register_portal_evidence,
)
from app.services.portal_acceptance_runtime import (
    stable_hash as portal_hash,
)
from app.services.production_acceptance_catalog import PRODUCTION_ACCEPTANCE_GATES
from app.services.production_acceptance_runtime import production_ready_from_evidence
from app.services.production_deployment_projection import evaluate_migration_state_evidence
from app.services.recovery_runtime import (
    physical_provider_execution_readiness,
    recovery_chain_correlated,
    recovery_evidence_freshness,
)


def _portal_evidence(validation_type: str, *, status: str = "passed", expired: bool = False):
    now = datetime.now(UTC)
    payload = PortalAcceptanceEvidenceCreate(
        scope="platform",
        validation_run_code="portal-run",
        validation_type=validation_type,
        status=status,
        source="external-governed-validation",
        evidence_payload={"validation_type": validation_type},
        started_at=now - timedelta(minutes=6),
        completed_at=now - timedelta(minutes=5),
        observed_at=now - timedelta(minutes=5),
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(hours=1),
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        **payload.model_dump(),
        evidence_hash=portal_hash(payload.model_dump(mode="json", exclude={"created_by"})),
    )


def _portal_repository(monkeypatch, evidence):
    class Repository:
        def __init__(self, db):
            pass

        def latest_run_code(self, scope, organization_id):
            return "portal-run" if evidence else None

        def list_evidence(self, scope, organization_id, **kwargs):
            return evidence

    monkeypatch.setattr("app.services.portal_acceptance_runtime.PortalAcceptanceRepository", Repository)


def test_portal_readiness_without_evidence_is_not_evaluated(monkeypatch) -> None:
    _portal_repository(monkeypatch, [])
    readiness = build_portal_acceptance_readiness(SimpleNamespace())
    assert readiness.status == "not_evaluated"
    assert all(item.status == "not_evaluated" for item in readiness.gate_results)


def test_portal_readiness_passes_only_with_all_six_fresh_types(monkeypatch) -> None:
    _portal_repository(monkeypatch, [_portal_evidence(item) for item in PORTAL_VALIDATION_TYPES])
    readiness = build_portal_acceptance_readiness(SimpleNamespace())
    assert readiness.status == "passed"
    assert len(readiness.gate_results) == 6

    _portal_repository(monkeypatch, [_portal_evidence(item) for item in PORTAL_VALIDATION_TYPES[:-1]])
    incomplete = build_portal_acceptance_readiness(SimpleNamespace())
    assert incomplete.status == "not_evaluated"
    assert incomplete.gate_results[-1].status == "not_evaluated"


def test_failed_and_expired_portal_evidence_fail_closed(monkeypatch) -> None:
    evidence = [_portal_evidence(item) for item in PORTAL_VALIDATION_TYPES]
    evidence[3] = _portal_evidence("negative_states", status="failed")
    _portal_repository(monkeypatch, evidence)
    assert build_portal_acceptance_readiness(SimpleNamespace()).status == "failed"

    evidence[3] = _portal_evidence("negative_states", expired=True)
    assert build_portal_acceptance_readiness(SimpleNamespace()).status == "expired"

    evidence[3] = _portal_evidence("negative_states")
    evidence[3].evidence_hash = "0" * 64
    corrupt = build_portal_acceptance_readiness(SimpleNamespace())
    assert corrupt.status == "failed"
    assert corrupt.reason == "contract_hardening_failed"


def test_portal_evidence_rejects_secrets_and_invalid_scope() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="secret material"):
        PortalAcceptanceEvidenceCreate(
            validation_run_code="run",
            validation_type="portal_build",
            status="passed",
            source="external",
            evidence_payload={"token": "unsafe"},
            started_at=now,
            completed_at=now,
            observed_at=now,
        )
    with pytest.raises(ValidationError, match="must be omitted"):
        PortalAcceptanceEvidenceCreate(
            scope="platform",
            organization_id=uuid.uuid4(),
            validation_run_code="run",
            validation_type="portal_build",
            status="blocked",
            source="external",
            evidence_payload={},
            started_at=now,
            observed_at=now,
        )


def test_portal_evidence_registration_is_idempotent_and_conflict_safe(monkeypatch) -> None:
    now = datetime.now(UTC)
    payload = PortalAcceptanceEvidenceCreate(
        validation_run_code="idempotent-run",
        validation_type="portal_contract",
        status="passed",
        source="external",
        evidence_payload={"contract_validated": True},
        started_at=now,
        completed_at=now,
        observed_at=now,
        created_by="tester",
    )
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        scope="platform",
        organization_id=None,
        validation_run_code=payload.validation_run_code,
        validation_type=payload.validation_type,
        status=payload.status,
        source=payload.source,
        source_reference=None,
        evidence_payload=payload.evidence_payload,
        evidence_hash=portal_hash(payload.model_dump(mode="json", exclude={"created_by"})),
        started_at=now,
        completed_at=now,
        observed_at=now,
        expires_at=None,
        created_by="tester",
        created_at=now,
    )

    class Repository:
        def __init__(self, db):
            pass

        def find_identity(self, *args):
            return existing

    monkeypatch.setattr("app.services.portal_acceptance_runtime.PortalAcceptanceRepository", Repository)
    result = register_portal_evidence(SimpleNamespace(), payload)
    assert result.id == existing.id

    conflict = payload.model_copy(update={"evidence_payload": {"contract_validated": False}})
    with pytest.raises(ValueError, match="portal_evidence_idempotency_conflict"):
        register_portal_evidence(SimpleNamespace(), conflict)


def test_recovery_chain_rejects_policy_and_verification_mismatch() -> None:
    organization_id = uuid.uuid4()
    policy = SimpleNamespace(id=uuid.uuid4(), scope="organization", organization_id=organization_id)
    backup = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=policy.id,
        scope=policy.scope,
        organization_id=organization_id,
    )
    restore = SimpleNamespace(
        id=uuid.uuid4(),
        policy_id=policy.id,
        backup_execution_id=backup.id,
        scope=policy.scope,
        organization_id=organization_id,
    )
    verification = SimpleNamespace(restore_execution_id=restore.id)
    assert recovery_chain_correlated(policy, backup, restore, verification) is True

    restore.policy_id = uuid.uuid4()
    assert recovery_chain_correlated(policy, backup, restore, verification) is False
    restore.policy_id = policy.id
    verification.restore_execution_id = uuid.uuid4()
    assert recovery_chain_correlated(policy, backup, restore, verification) is False

    verification.restore_execution_id = restore.id
    restore.organization_id = uuid.uuid4()
    assert recovery_chain_correlated(policy, backup, restore, verification) is False


def test_recovery_expiration_and_physical_provider_evidence_remain_distinct() -> None:
    now = datetime.now(UTC)
    policy = SimpleNamespace(evidence_max_age_hours=1)
    backup = SimpleNamespace(completed_at=now - timedelta(hours=2), provider_execution_id=None)
    verification = SimpleNamespace(completed_at=now - timedelta(minutes=10))
    restore = SimpleNamespace(provider_execution_id="restore-provider-execution")

    backup_fresh, verification_fresh = recovery_evidence_freshness(policy, backup, verification, now)
    assert backup_fresh is False
    assert verification_fresh is True
    assert physical_provider_execution_readiness(backup, restore) == {
        "backup_evidenced": False,
        "restore_evidenced": True,
        "required_by_recovery_control_plane": False,
    }


def test_operational_freshness_and_incident_status_are_explicit() -> None:
    now = datetime.now(UTC)
    fresh_critical = SimpleNamespace(
        severity="critical",
        status="failed",
        expires_at=now + timedelta(minutes=5),
    )
    expired_critical = SimpleNamespace(
        severity="critical",
        status="failed",
        expires_at=now - timedelta(seconds=1),
    )
    resolved_incident = SimpleNamespace(severity="critical", status="resolved")
    open_incident = SimpleNamespace(severity="critical", status="open")
    healthy_component = SimpleNamespace(status="running", last_heartbeat_at=now)

    signals = current_critical_operational_signals(
        [healthy_component],
        [fresh_critical, expired_critical],
        [resolved_incident],
        now,
    )
    assert signals["observations"] == [fresh_critical]
    assert signals["incidents"] == []

    signals = current_critical_operational_signals(
        [healthy_component],
        [expired_critical],
        [open_incident],
        now,
    )
    assert signals["observations"] == []
    assert signals["incidents"] == [open_incident]


def test_catalog_has_no_duplicate_or_missing_mandatory_gates() -> None:
    codes = [gate.gate_code for gate in PRODUCTION_ACCEPTANCE_GATES]
    assert len(codes) == len(set(codes))
    assert all(gate.mandatory for gate in PRODUCTION_ACCEPTANCE_GATES)


def test_production_ready_requires_passed_preflight() -> None:
    gates = [SimpleNamespace(mandatory=True, status="passed")]
    blocked_preflight = SimpleNamespace(status="blocked", blockers=[{"code": "unsafe_local"}])
    passed_preflight = SimpleNamespace(status="passed", blockers=[])
    assert production_ready_from_evidence(gates, blocked_preflight) is False
    assert production_ready_from_evidence(gates, passed_preflight) is True


def test_migration_state_requires_revision_pending_count_and_release_build_correlation() -> None:
    release_id = uuid.uuid4()
    build_id = uuid.uuid4()
    manifest_id = uuid.uuid4()
    requirement = SimpleNamespace(
        from_revision="930",
        to_revision="940",
        evidence_payload={
            "repository_target_revision": "940",
            "database_current_revision": "940",
            "single_alembic_head": True,
            "pending_migrations_count": 0,
            "schema_compatibility_status": "compatible",
            "release_id": str(release_id),
            "build_id": str(build_id),
            "build_manifest_id": str(manifest_id),
            "from_revision": "930",
            "to_revision": "940",
        },
    )
    compatibility = [SimpleNamespace(compatible=True)]
    clean, checks = evaluate_migration_state_evidence(
        current_revisions=["940"],
        target_revision="940",
        migration_requirement=requirement,
        database_compatibility=compatibility,
        release_id=release_id,
        build_id=build_id,
        build_manifest_id=manifest_id,
        deployment_build_id=build_id,
        acceptance_status="passed",
    )
    assert clean is True
    assert all(checks.values())

    requirement.evidence_payload["pending_migrations_count"] = 1
    clean, checks = evaluate_migration_state_evidence(
        current_revisions=["940"],
        target_revision="940",
        migration_requirement=requirement,
        database_compatibility=compatibility,
        release_id=release_id,
        build_id=build_id,
        build_manifest_id=manifest_id,
        deployment_build_id=build_id,
        acceptance_status="passed",
    )
    assert clean is False
    assert checks["pending_migrations_zero"] is False

    requirement.evidence_payload["pending_migrations_count"] = 0
    clean, checks = evaluate_migration_state_evidence(
        current_revisions=["930"],
        target_revision="940",
        migration_requirement=requirement,
        database_compatibility=compatibility,
        release_id=release_id,
        build_id=build_id,
        build_manifest_id=manifest_id,
        deployment_build_id=build_id,
        acceptance_status="passed",
    )
    assert clean is False
    assert checks["database_at_expected_revision"] is False

    requirement.evidence_payload["build_id"] = str(uuid.uuid4())
    clean, checks = evaluate_migration_state_evidence(
        current_revisions=["940"],
        target_revision="940",
        migration_requirement=requirement,
        database_compatibility=compatibility,
        release_id=release_id,
        build_id=build_id,
        build_manifest_id=manifest_id,
        deployment_build_id=build_id,
        acceptance_status="passed",
    )
    assert clean is False
    assert checks["build_correlated"] is False
