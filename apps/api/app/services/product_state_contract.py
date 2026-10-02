from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def evidence_freshness(
    *,
    acceptance_status: str | None,
    expires_at: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not acceptance_status:
        return {"status": "unavailable", "reason": "No applicable Product Acceptance evidence exists."}
    normalized = acceptance_status.strip().lower()
    if normalized == "expired":
        return {"status": "expired", "reason": "Product Acceptance evidence has expired."}
    if normalized == "stale":
        return {"status": "stale", "reason": "Product Acceptance evidence is stale."}
    expiry = _as_datetime(expires_at)
    if expiry is None:
        return {
            "status": "unavailable",
            "reason": "Applicable Product Acceptance evidence has no governed expiration.",
        }
    current_time = now or datetime.now(UTC)
    if expiry <= current_time:
        return {"status": "expired", "reason": "Product Acceptance evidence has expired."}
    return {
        "status": "current",
        "reason": "Product Acceptance evidence is within its governed validity period.",
    }


def build_product_state_contract(
    result: Any | None,
    *,
    persisted_run_status: str | None,
    evaluated_release_version: str,
    evidence_release_version: str | None,
    evidence_applicable: bool,
    release_evidence_expires_at: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if result is None:
        return {
            "product_acceptance": {
                "status": "unavailable",
                "historical_result": "unavailable",
                "reason": "No applicable persisted Product Acceptance run exists.",
            },
            "evidence_freshness": evidence_freshness(acceptance_status=None, expires_at=None, now=now),
            "release_eligibility": {
                "eligible": False,
                "status": "unavailable",
                "reason": "Current Product Acceptance evidence is required.",
                "blocking_reasons": ["product_acceptance_evidence_missing"],
                "evaluated_release_version": evaluated_release_version,
                "evidence_release_version": None,
            },
        }

    current_run_status = str(_value(result, "status", "unavailable") or "unavailable").lower()
    functional_acceptance = _value(result, "functional_acceptance", {}) or {}
    persisted_acceptance_status = str(
        _value(functional_acceptance, "status", persisted_run_status or current_run_status)
        or "unavailable"
    ).lower()
    expirations = [
        expiration
        for expiration in (
            _as_datetime(_value(result, "expires_at")),
            _as_datetime(release_evidence_expires_at),
        )
        if expiration is not None
    ]
    effective_expiration = min(expirations) if expirations else None
    freshness = evidence_freshness(
        acceptance_status=current_run_status,
        expires_at=effective_expiration,
        now=now,
    )
    acceptance_status = (
        "unavailable"
        if persisted_acceptance_status in {"not_evaluated", "interrupted", "pending", "running"}
        else persisted_acceptance_status
    )
    if freshness["status"] == "expired" and persisted_acceptance_status == "passed":
        acceptance_status = "expired"
    elif freshness["status"] == "stale" and persisted_acceptance_status == "passed":
        acceptance_status = "stale"
    blocking_reasons: list[str] = []
    if acceptance_status != "passed":
        blocking_reasons.append(f"product_acceptance_{acceptance_status}")
    if freshness["status"] != "current":
        blocking_reasons.append(f"evidence_{freshness['status']}")
    if _value(result, "production_ready") is not True:
        blocking_reasons.append("mandatory_production_gates_not_passed")
    mandatory_counts = _value(result, "mandatory_gate_counts", {}) or {}
    if any(int(mandatory_counts.get(key) or 0) > 0 for key in ("failed", "blocked", "not_evaluated")):
        blocking_reasons.append("mandatory_gate_blocked_or_failed")
    if not evidence_applicable:
        blocking_reasons.append("release_evidence_not_applicable")
    if evidence_release_version is None:
        blocking_reasons.append("release_version_evidence_missing")
    elif evidence_release_version != evaluated_release_version:
        blocking_reasons.append("release_candidate_version_mismatch")
    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    eligible = not blocking_reasons
    return {
        "product_acceptance": {
            "status": acceptance_status,
            "historical_result": persisted_acceptance_status,
            "reason": f"local_product_acceptance_{acceptance_status}",
            "evaluation_timestamp": _value(result, "evaluation_timestamp"),
        },
        "evidence_freshness": {
            **freshness,
            "expires_at": effective_expiration,
        },
        "release_eligibility": {
            "eligible": eligible,
            "status": "eligible" if eligible else "not_eligible",
            "reason": (
                "All persisted release gates passed with current evidence for this release candidate."
                if eligible
                else "Current applicable Product Acceptance evidence does not permit release eligibility."
            ),
            "blocking_reasons": blocking_reasons,
            "evaluated_release_version": evaluated_release_version,
            "evidence_release_version": evidence_release_version,
        },
    }
