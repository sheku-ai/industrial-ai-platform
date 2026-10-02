from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.recovery_provider_execution import ProviderExecutionEvidenceCreate
from app.services.recovery_provider_execution_evidence import register_provider_execution_evidence


class FakeSession:
    def __init__(self) -> None:
        self.evidence = None
        self.add_count = 0

    def scalar(self, statement):  # noqa: ANN001, ARG002
        return self.evidence

    def add(self, evidence):  # noqa: ANN001
        self.add_count += 1
        self.evidence = evidence

    def flush(self) -> None:
        if self.evidence is not None and self.evidence.id is None:
            self.evidence.id = uuid.uuid4()


def _payload(**updates):  # noqa: ANN003
    started_at = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    values = {
        "scope": "platform",
        "organization_id": None,
        "operation": "backup",
        "resource_type": "platform_postgresql",
        "execution_entity_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "provider_type": "external_evidence",
        "provider_execution_id": "backup-provider-001",
        "execution_status": "completed",
        "started_at": started_at,
        "completed_at": started_at + timedelta(minutes=3),
        "observed_at": started_at + timedelta(minutes=4),
        "evidence_source": "backup-system",
        "correlation_id": "recovery:test:001",
        "idempotency_key": "provider-evidence-001",
        "reference_payload": {"job": "backup-provider-001"},
    }
    values.update(updates)
    return ProviderExecutionEvidenceCreate(**values)


def test_provider_execution_evidence_is_persisted_with_authoritative_identity() -> None:
    db = FakeSession()

    result = register_provider_execution_evidence(db, _payload())

    assert db.add_count == 1
    assert result.operation == "backup"
    assert result.resource_type == "platform_postgresql"
    assert result.provider_execution_id == "backup-provider-001"
    assert len(result.evidence_hash) == 64
    assert db.evidence.status == "passed"


def test_provider_execution_evidence_replay_is_idempotent() -> None:
    db = FakeSession()
    payload = _payload()

    first = register_provider_execution_evidence(db, payload)
    second = register_provider_execution_evidence(db, payload)

    assert db.add_count == 1
    assert second.id == first.id
    assert second.evidence_hash == first.evidence_hash


def test_provider_execution_evidence_rejects_conflicting_replay() -> None:
    db = FakeSession()
    payload = _payload()
    register_provider_execution_evidence(db, payload)

    with pytest.raises(ValueError, match="provider_evidence_idempotency_conflict"):
        register_provider_execution_evidence(
            db,
            _payload(provider_execution_id="different-provider-run"),
        )


def test_legacy_postgresql_cannot_be_registered_as_authoritative_provider_evidence() -> None:
    with pytest.raises(ValueError, match="legacy_recovery_resource_not_authoritative"):
        register_provider_execution_evidence(FakeSession(), _payload(resource_type="postgresql"))


def test_provider_execution_evidence_enforces_scope_and_timestamp_consistency() -> None:
    organization_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    with pytest.raises(ValueError, match="platform_scope_must_not_have_organization"):
        register_provider_execution_evidence(FakeSession(), _payload(organization_id=organization_id))

    started_at = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="provider_evidence_completion_precedes_start"):
        register_provider_execution_evidence(
            FakeSession(),
            _payload(started_at=started_at, completed_at=started_at - timedelta(minutes=1)),
        )
