from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.recovery import RestoreVerificationCompleteRequest
from app.services import recovery_authoritative_verification as authoritative_verification
from app.services.recovery_verification_evidence import REQUIRED_VERIFICATION_CHECKS


def _restore():  # noqa: ANN202
    return SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        scope="platform",
        organization_id=None,
        correlation_id="recovery:verification:001",
        status="completed",
    )


def _verification():  # noqa: ANN202
    return SimpleNamespace(id=uuid.UUID("22222222-2222-2222-2222-222222222222"))


def _all_true_payload() -> RestoreVerificationCompleteRequest:
    return RestoreVerificationCompleteRequest(
        **{check_code: True for check_code in REQUIRED_VERIFICATION_CHECKS},
        verification_payload={"submitted": "context"},
    )


def test_all_true_flags_do_not_replace_missing_authoritative_evidence(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        authoritative_verification,
        "restore_verification_check_evidence_for",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="database_connectivity_verified_evidence_missing"):
        authoritative_verification.complete_restore_verification(
            SimpleNamespace(),
            SimpleNamespace(),
            _restore(),
            _verification(),
            _all_true_payload(),
        )


def test_authoritative_evidence_derives_all_verification_flags(monkeypatch) -> None:  # noqa: ANN001
    captured = {}

    def evidence_for(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return SimpleNamespace(
            id=uuid.uuid4(),
            evidence_payload={"correlation_id": "recovery:verification:001"},
        )

    def legacy_complete(db, policy, restore, verification, payload):  # noqa: ANN001, ANN202
        captured["payload"] = payload
        return "completed"

    monkeypatch.setattr(
        authoritative_verification,
        "restore_verification_check_evidence_for",
        evidence_for,
    )
    monkeypatch.setattr(
        authoritative_verification,
        "complete_restore_verification_legacy",
        legacy_complete,
    )

    submitted = RestoreVerificationCompleteRequest(
        verification_payload={"operator_note": "not authoritative"},
    )
    result = authoritative_verification.complete_restore_verification(
        SimpleNamespace(),
        SimpleNamespace(),
        _restore(),
        _verification(),
        submitted,
    )

    assert result == "completed"
    for check_code in REQUIRED_VERIFICATION_CHECKS:
        assert getattr(captured["payload"], check_code) is True
    assert set(captured["payload"].verification_payload["authoritative_check_evidence"]) == set(
        REQUIRED_VERIFICATION_CHECKS
    )
    assert captured["payload"].verification_payload["submitted_context"] == {"operator_note": "not authoritative"}


def test_verification_evidence_must_match_restore_correlation(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        authoritative_verification,
        "restore_verification_check_evidence_for",
        lambda *args, **kwargs: SimpleNamespace(
            id=uuid.uuid4(),
            evidence_payload={"correlation_id": "different-correlation"},
        ),
    )

    with pytest.raises(ValueError, match="database_connectivity_verified_correlation_mismatch"):
        authoritative_verification.complete_restore_verification(
            SimpleNamespace(),
            SimpleNamespace(),
            _restore(),
            _verification(),
            _all_true_payload(),
        )
