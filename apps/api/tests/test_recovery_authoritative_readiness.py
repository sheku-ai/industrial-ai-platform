from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import recovery_objectives_runtime as runtime
from app.services.recovery_verification_evidence import REQUIRED_VERIFICATION_CHECKS


class FakeRepository:
    def __init__(self, _db) -> None:  # noqa: ANN001
        self.policy = SimpleNamespace(
            id=uuid.uuid4(),
            scope="platform",
            database_backup_enabled=True,
            object_storage_backup_enabled=True,
            configuration_backup_enabled=True,
        )
        self.backup = SimpleNamespace(
            id=uuid.uuid4(),
            scope="platform",
            organization_id=None,
            provider_type="external_evidence",
            correlation_id="backup:001",
        )
        self.restore = SimpleNamespace(
            id=uuid.uuid4(),
            scope="platform",
            organization_id=None,
            provider_type="external_evidence",
            correlation_id="restore:001",
            backup_execution_id=self.backup.id,
        )
        self.verification = SimpleNamespace(
            id=uuid.uuid4(),
            restore_execution_id=self.restore.id,
        )

    def active_policy(self, scope, organization_id):  # noqa: ANN001, ARG002
        return self.policy

    def latest_completed_backup_for_policy(self, policy_id, scope, organization_id):  # noqa: ANN001, ARG002
        return self.backup

    def latest_completed_restore_for_policy(self, policy_id, scope, organization_id):  # noqa: ANN001, ARG002
        return self.restore

    def latest_passed_verification_for_restore(self, restore_id):  # noqa: ANN001, ARG002
        return self.verification


def _provider_evidence(operation: str, resource_type: str, execution) -> SimpleNamespace:  # noqa: ANN001
    return SimpleNamespace(
        evidence_payload={
            "operation": operation,
            "resource_type": resource_type,
            "provider_type": execution.provider_type,
            "provider_execution_id": f"{operation}:{resource_type}:001",
            "correlation_id": execution.correlation_id,
        }
    )


def test_historical_completed_chain_without_provider_evidence_is_not_authoritative(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(runtime, "RecoveryRepository", FakeRepository)
    monkeypatch.setattr(runtime, "provider_execution_evidence_for", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "restore_verification_check_evidence_for", lambda *args, **kwargs: None)

    result = runtime.authoritative_recovery_chain(object(), scope="platform", organization_id=None)

    assert result.backup_evidenced is False
    assert result.restore_evidenced is False
    assert result.verification_evidenced is False
    assert result.ready is False


def test_missing_single_verification_check_blocks_authoritative_chain(monkeypatch) -> None:  # noqa: ANN001
    repo = FakeRepository(None)
    monkeypatch.setattr(runtime, "RecoveryRepository", lambda _db: repo)

    def provider_evidence(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        execution = repo.backup if kwargs["operation"] == "backup" else repo.restore
        return _provider_evidence(kwargs["operation"], kwargs["resource_type"], execution)

    def verification_evidence(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if kwargs["check_code"] == REQUIRED_VERIFICATION_CHECKS[-1]:
            return None
        return SimpleNamespace(evidence_payload={"correlation_id": repo.restore.correlation_id})

    monkeypatch.setattr(runtime, "provider_execution_evidence_for", provider_evidence)
    monkeypatch.setattr(runtime, "restore_verification_check_evidence_for", verification_evidence)

    result = runtime.authoritative_recovery_chain(object(), scope="platform", organization_id=None)

    assert result.backup_evidenced is True
    assert result.restore_evidenced is True
    assert result.verification_evidenced is False
    assert result.ready is False


def test_all_required_provider_and_verification_evidence_makes_chain_authoritative(monkeypatch) -> None:  # noqa: ANN001
    repo = FakeRepository(None)
    monkeypatch.setattr(runtime, "RecoveryRepository", lambda _db: repo)

    def provider_evidence(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        execution = repo.backup if kwargs["operation"] == "backup" else repo.restore
        return _provider_evidence(kwargs["operation"], kwargs["resource_type"], execution)

    monkeypatch.setattr(runtime, "provider_execution_evidence_for", provider_evidence)
    monkeypatch.setattr(
        runtime,
        "restore_verification_check_evidence_for",
        lambda *args, **kwargs: SimpleNamespace(
            evidence_payload={"correlation_id": repo.restore.correlation_id}
        ),
    )

    result = runtime.authoritative_recovery_chain(object(), scope="platform", organization_id=None)

    assert result.backup_evidenced is True
    assert result.restore_evidenced is True
    assert result.verification_evidenced is True
    assert result.ready is True
