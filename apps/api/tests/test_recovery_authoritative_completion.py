from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.recovery import BackupCompleteRequest, RestoreCompleteRequest
from app.services import recovery_authoritative_completion as completion


def _policy() -> Any:
    return SimpleNamespace(
        scope="platform",
        database_backup_enabled=True,
        object_storage_backup_enabled=True,
        configuration_backup_enabled=True,
    )


def _execution() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope="platform",
        organization_id=None,
        provider_type="external_evidence",
        correlation_id="corr-1",
    )


def _evidence(resource_type: str, execution: Any) -> Any:
    return SimpleNamespace(
        evidence_payload={
            "resource_type": resource_type,
            "provider_type": execution.provider_type,
            "provider_execution_id": f"provider-{resource_type}",
            "correlation_id": execution.correlation_id,
        }
    )


def test_backup_completion_blocks_when_provider_evidence_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    execution = _execution()
    monkeypatch.setattr(completion, "provider_execution_evidence_for", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="platform_postgresql_provider_execution_evidence_missing"):
        completion.complete_backup_execution(None, _policy(), execution, BackupCompleteRequest())


def test_restore_flags_are_derived_from_provider_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    execution = _execution()

    def evidence_for(*args: Any, **kwargs: Any) -> Any:
        return _evidence(kwargs["resource_type"], execution)

    captured: dict[str, Any] = {}

    def legacy(db: Any, policy: Any, restore: Any, payload: RestoreCompleteRequest) -> Any:
        captured["payload"] = payload
        return "completed"

    monkeypatch.setattr(completion, "provider_execution_evidence_for", evidence_for)
    monkeypatch.setattr(completion, "complete_restore_execution_legacy", legacy)

    result = completion.complete_restore_execution(
        None,
        _policy(),
        execution,
        RestoreCompleteRequest(
            database_restored=False,
            object_storage_restored=False,
            configuration_restored=False,
        ),
    )

    assert result == "completed"
    assert captured["payload"].database_restored is True
    assert captured["payload"].object_storage_restored is True
    assert captured["payload"].configuration_restored is True


def test_declared_true_restore_flags_do_not_replace_missing_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    execution = _execution()

    def evidence_for(*args: Any, **kwargs: Any) -> Any:
        if kwargs["resource_type"] == "identity_postgresql":
            return None
        return _evidence(kwargs["resource_type"], execution)

    monkeypatch.setattr(completion, "provider_execution_evidence_for", evidence_for)

    with pytest.raises(ValueError, match="identity_postgresql_provider_execution_evidence_missing"):
        completion.complete_restore_execution(
            None,
            _policy(),
            execution,
            RestoreCompleteRequest(
                database_restored=True,
                object_storage_restored=True,
                configuration_restored=True,
            ),
        )


def test_provider_evidence_must_match_execution_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    execution = _execution()

    def evidence_for(*args: Any, **kwargs: Any) -> Any:
        evidence = _evidence(kwargs["resource_type"], execution)
        evidence.evidence_payload["provider_type"] = "filesystem"
        return evidence

    monkeypatch.setattr(completion, "provider_execution_evidence_for", evidence_for)

    with pytest.raises(ValueError, match="platform_postgresql_provider_execution_provider_mismatch"):
        completion.complete_backup_execution(None, _policy(), execution, BackupCompleteRequest())
