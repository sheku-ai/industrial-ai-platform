from __future__ import annotations

from typing import Any

REQUIRED_READINESS_FIELDS = {
    "status",
    "reason",
    "blockers",
    "warnings",
    "recommendations",
    "next_actions",
    "contract_version",
    "runtime_version",
    "evaluation_timestamp",
    "expires_at",
    "evidence_origin",
    "evaluation_duration",
    "components_evaluated",
    "evidence_ids",
}


def public_readiness_contract_valid(payload: Any, *, domain: str | None = None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not REQUIRED_READINESS_FIELDS.issubset(payload):
        return False
    if payload.get("contract_version") != "platform.readiness.evidence.v1":
        return False
    if domain is not None and payload.get("domain") != domain:
        return False
    list_fields = (
        "gate_results",
        "blockers",
        "warnings",
        "recommendations",
        "next_actions",
        "components_evaluated",
        "evidence_ids",
    )
    return (
        payload.get("status")
        in {"passed", "failed", "blocked", "not_evaluated", "expired", "stale", "interrupted"}
        and isinstance(payload.get("reason"), str)
        and bool(payload.get("reason"))
        and all(isinstance(payload.get(field), list) for field in list_fields)
        and payload.get("postgresql_source_of_truth") is True
    )
