"""Release-readiness projection for the complete platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_acceptance import build_platform_journey_acceptance

RELEASE_READINESS_SCHEMA_VERSION = "1"


def _release_status(acceptance: dict[str, Any]) -> str:
    acceptance_status = acceptance["acceptance_status"]
    if acceptance["blocking_failures"]:
        return "blocked"
    if acceptance_status == "accepted_with_optional_degradation":
        return "ready_with_optional_degradation"
    if acceptance_status == "accepted":
        return "ready"
    return "blocked"


def _required_operator_checks(validation_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for step in validation_plan["steps"]:
        checks.append(
            {
                "sequence": step["sequence"],
                "name": step["name"],
                "status": step["status"],
                "blocking": step["blocking"],
                "command": step["command"],
                "route": step["route"],
                "expected_signal": step["expected_signal"],
                "destructive": False,
                "executes_migrations": False,
            }
        )
    return checks


def build_platform_journey_release_readiness_from_acceptance(
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    """Build release-readiness from the existing acceptance projection."""

    validation_plan = acceptance["validation_plan"]
    return {
        "plan": "platform_product_journey_release_readiness",
        "release_readiness_schema_version": RELEASE_READINESS_SCHEMA_VERSION,
        "timestamp_utc": acceptance["timestamp_utc"],
        "platform": acceptance["platform"],
        "release_readiness_status": _release_status(acceptance),
        "acceptance_status": acceptance["acceptance_status"],
        "decision": acceptance["decision"],
        "operator_validation_ready": acceptance["ready_for_operator_validation"],
        "blocking_failures": acceptance["blocking_failures"],
        "warnings": acceptance["warnings"],
        "degraded_capabilities": acceptance["degraded_capabilities"],
        "required_operator_checks": _required_operator_checks(validation_plan),
        "evidence_consistency_status": acceptance["evidence_consistency_status"],
        "safe_to_run_without_ai": acceptance["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "primary_action": acceptance["primary_action"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_release_readiness(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    acceptance = build_platform_journey_acceptance(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_release_readiness_from_acceptance(acceptance)
