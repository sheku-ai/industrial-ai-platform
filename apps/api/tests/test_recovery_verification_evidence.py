from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.recovery_verification_evidence import RestoreVerificationCheckEvidenceCreate
from app.services.recovery_verification_evidence import register_restore_verification_check_evidence


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
    values = {
        "check_code": "database_connectivity_verified",
        "check_status": "passed",
        "observed_at": datetime(2026, 8, 26, 0, 0, tzinfo=UTC),
        "evidence_source": "recovery-validator",
        "correlation_id": "recovery:verification:001",
        "idempotency_key": "verification-check-001",
        "reference_payload": {"probe": "database-connectivity", "result": "passed"},
    }
    values.update(updates)
    return RestoreVerificationCheckEvidenceCreate(**values)


def test_restore_verification_check_evidence_is_persisted() -> None:
    db = FakeSession()
    verification_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    result = register_restore_verification_check_evidence(
        db,
        scope="platform",
        organization_id=None,
        verification_id=verification_id,
        payload=_payload(),
    )

    assert db.add_count == 1
    assert result.verification_id == verification_id
    assert result.check_code == "database_connectivity_verified"
    assert result.check_status == "passed"
    assert db.evidence.status == "passed"
    assert len(result.evidence_hash) == 64


def test_restore_verification_check_evidence_replay_is_idempotent() -> None:
    db = FakeSession()
    verification_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    payload = _payload()

    first = register_restore_verification_check_evidence(
        db,
        scope="platform",
        organization_id=None,
        verification_id=verification_id,
        payload=payload,
    )
    second = register_restore_verification_check_evidence(
        db,
        scope="platform",
        organization_id=None,
        verification_id=verification_id,
        payload=payload,
    )

    assert db.add_count == 1
    assert second.id == first.id
    assert second.evidence_hash == first.evidence_hash


def test_restore_verification_check_evidence_rejects_conflicting_replay() -> None:
    db = FakeSession()
    verification_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    register_restore_verification_check_evidence(
        db,
        scope="platform",
        organization_id=None,
        verification_id=verification_id,
        payload=_payload(),
    )

    with pytest.raises(ValueError, match="restore_verification_evidence_idempotency_conflict"):
        register_restore_verification_check_evidence(
            db,
            scope="platform",
            organization_id=None,
            verification_id=verification_id,
            payload=_payload(check_status="failed"),
        )


def test_restore_verification_check_evidence_rejects_unknown_check() -> None:
    with pytest.raises(ValueError, match="restore_verification_check_not_supported"):
        register_restore_verification_check_evidence(
            FakeSession(),
            scope="platform",
            organization_id=None,
            verification_id=uuid.uuid4(),
            payload=_payload(check_code="caller_declared_check"),
        )
