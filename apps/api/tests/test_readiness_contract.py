from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.readiness_contract import build_readiness_evidence


def test_authoritative_readiness_contract_preserves_persisted_evidence_identity() -> None:
    evaluated_at = datetime.now(UTC)
    evidence = build_readiness_evidence(
        domain="capacity",
        status="passed",
        gate_results=[
            {
                "gate_code": "capacity_validated",
                "status": "passed",
                "summary": "Persisted capacity evidence passed.",
                "evidence_reference": "evidence-1",
            }
        ],
        blockers=[],
        warnings=[],
        runtime_version="capacity-runtime.v1",
        evaluation_timestamp=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=24),
        evidence_origin="capacity_load_evidence_runtime",
        evaluation_duration=17,
        components_evaluated=["database"],
        evidence_ids=["evaluation-1"],
    )

    assert evidence.contract_version == "platform.readiness.evidence.v1"
    assert evidence.evaluation_timestamp == evaluated_at
    assert evidence.evaluation_duration == 17
    assert evidence.components_evaluated == ["capacity_validated", "database"]
    assert evidence.evidence_ids == ["evaluation-1", "evidence-1"]
    assert evidence.gate_results[0].evidence_ids == ["evidence-1"]


def test_authoritative_readiness_contract_rejects_corrupt_and_incompatible_evidence() -> None:
    evaluated_at = datetime.now(UTC)
    evidence = build_readiness_evidence(
        domain="security",
        status="passed",
        gate_results=[{"gate_code": "security_validated", "status": "passed", "summary": "Passed."}],
        blockers=[],
        warnings=[],
        runtime_version="security-acceptance-runtime.v2",
        evaluation_timestamp=evaluated_at,
        expires_at=evaluated_at + timedelta(hours=1),
        evidence_origin="security_acceptance_runtime",
        source_contract_version="unknown.contract.v9",
        supported_contract_versions=("security.evidence.v1",),
        source_runtime_version="security-runtime.v0",
        supported_runtime_versions=("security-acceptance-runtime.v2",),
        integrity_errors=[{"code": "evidence_hash_mismatch", "message": "Persisted evidence hash mismatch."}],
    )

    assert evidence.status == "failed"
    assert evidence.reason == "contract_hardening_failed"
    assert evidence.gate_results[0].status == "failed"
    assert {item["code"] for item in evidence.blockers} == {
        "unsupported_contract_version",
        "incompatible_runtime_version",
        "evidence_hash_mismatch",
    }


def test_authoritative_readiness_contract_preserves_expired_state() -> None:
    now = datetime.now(UTC)
    evidence = build_readiness_evidence(
        domain="portal",
        status="expired",
        gate_results=[{"gate_code": "portal_contract", "status": "blocked", "summary": "Expired."}],
        blockers=[{"code": "portal_evidence_expired"}],
        warnings=[],
        runtime_version="portal-acceptance-runtime.v1",
        evaluation_timestamp=now,
        expires_at=now - timedelta(minutes=1),
        evidence_origin="portal_acceptance_evidence_runtime",
    )

    assert evidence.status == "expired"
    assert evidence.reason == "authoritative_evidence_expired"
    assert not any(item.get("code") == "invalid_evidence_lifetime" for item in evidence.blockers)


def test_authoritative_readiness_contract_normalizes_partial_timestamps_and_statuses() -> None:
    naive = datetime.now().replace(microsecond=0)
    evidence = build_readiness_evidence(
        domain="capacity",
        status="unknown",
        gate_results=[{"gate_code": "capacity_validated", "status": "unknown", "summary": "Unknown."}],
        blockers=[],
        warnings=[],
        runtime_version="capacity-runtime.v1",
        evaluation_timestamp=naive,
        expires_at=naive + timedelta(hours=1),
        evidence_origin="capacity_load_evidence_runtime",
        evaluation_duration=-1,
    )

    assert evidence.status == "failed"
    assert evidence.evaluation_timestamp.tzinfo is not None
    assert evidence.evaluation_duration == 0
    assert evidence.gate_results[0].status == "failed"
    assert {item["code"] for item in evidence.blockers}.issuperset(
        {
            "invalid_readiness_status",
            "invalid_gate_status",
            "invalid_evaluation_timestamp",
            "invalid_evaluation_duration",
        }
    )
