from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services import recovery_objectives_runtime as runtime


class FakeRepository:
    def __init__(self, _db) -> None:  # noqa: ANN001
        base = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)
        self.policy = SimpleNamespace(id=uuid.uuid4())
        self.backup = SimpleNamespace(id=uuid.uuid4(), completed_at=base)
        self.restore = SimpleNamespace(
            id=uuid.uuid4(),
            backup_execution_id=self.backup.id,
            started_at=base + timedelta(minutes=12),
        )
        self.verification = SimpleNamespace(completed_at=base + timedelta(minutes=32))

    def active_policy(self, scope, organization_id):  # noqa: ANN001, ARG002
        return self.policy

    def latest_completed_backup_for_policy(self, policy_id, scope, organization_id):  # noqa: ANN001, ARG002
        return self.backup

    def latest_completed_restore_for_policy(self, policy_id, scope, organization_id):  # noqa: ANN001, ARG002
        return self.restore

    def latest_passed_verification_for_restore(self, restore_id):  # noqa: ANN001, ARG002
        return self.verification


def test_observed_recovery_objectives_are_derived_from_persisted_chain(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(runtime, "RecoveryRepository", FakeRepository)

    result = runtime.observed_recovery_objectives(object(), scope="platform", organization_id=None)

    assert result.rpo_minutes == 12.0
    assert result.rto_minutes == 20.0


def test_minutes_between_rejects_missing_or_inverted_timestamps() -> None:
    now = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)

    assert runtime._minutes_between(None, now) is None
    assert runtime._minutes_between(now, None) is None
    assert runtime._minutes_between(now, now - timedelta(minutes=1)) is None


def test_objective_thresholds_distinguish_rpo_and_rto() -> None:
    objectives = runtime.ObservedRecoveryObjectives(rpo_minutes=12.0, rto_minutes=20.0)

    assert objectives.rpo_minutes <= 15
    assert not objectives.rpo_minutes <= 10
    assert objectives.rto_minutes <= 25
    assert not objectives.rto_minutes <= 15


def test_incomplete_recovery_chain_does_not_invent_observed_metrics(monkeypatch) -> None:  # noqa: ANN001
    class IncompleteRepository(FakeRepository):
        def latest_completed_restore_for_policy(self, policy_id, scope, organization_id):  # noqa: ANN001, ARG002
            return None

    monkeypatch.setattr(runtime, "RecoveryRepository", IncompleteRepository)

    result = runtime.observed_recovery_objectives(object(), scope="platform", organization_id=None)

    assert result.rpo_minutes is None
    assert result.rto_minutes is None
