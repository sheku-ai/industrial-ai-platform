"""Completion report projection for the complete platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_release_readiness import build_platform_journey_release_readiness

COMPLETION_REPORT_SCHEMA_VERSION = "1"


def _completion_status(release_readiness: dict[str, Any]) -> str:
    status = release_readiness["release_readiness_status"]
    if status == "ready":
        return "complete"
    if status == "ready_with_optional_degradation":
        return "complete_with_optional_degradation"
    return "blocked"


def _next_recommended_step(release_readiness: dict[str, Any]) -> str:
    if release_readiness["blocking_failures"]:
        primary_action = release_readiness.get("primary_action") or {}
        return str(primary_action.get("name") or "resolve_blocking_failures")
    if release_readiness["evidence_consistency_status"] != "in_sync":
        return "write_journey_evidence"
    if release_readiness["warnings"] or release_readiness["degraded_capabilities"]:
        return "review_optional_degradations"
    return "ready_for_manual_release_review"


def _final_operator_summary(release_readiness: dict[str, Any]) -> dict[str, Any]:
    checks = release_readiness["required_operator_checks"]
    blocking_checks = [check for check in checks if check["blocking"] and check["status"] in {"blocked", "hold"}]
    return {
        "completion_status": _completion_status(release_readiness),
        "release_readiness_status": release_readiness["release_readiness_status"],
        "acceptance_status": release_readiness["acceptance_status"],
        "decision": release_readiness["decision"],
        "operator_validation_ready": release_readiness["operator_validation_ready"],
        "safe_to_run_without_ai": release_readiness["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "evidence_consistency_status": release_readiness["evidence_consistency_status"],
        "blocking_failure_count": len(release_readiness["blocking_failures"]),
        "warning_count": len(release_readiness["warnings"]),
        "degraded_capability_count": len(release_readiness["degraded_capabilities"]),
        "required_operator_check_count": len(checks),
        "blocking_operator_check_count": len(blocking_checks),
    }


def build_platform_journey_completion_report_from_release_readiness(
    release_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic completion report from release-readiness."""

    return {
        "plan": "platform_product_journey_completion_report",
        "completion_report_schema_version": COMPLETION_REPORT_SCHEMA_VERSION,
        "timestamp_utc": release_readiness["timestamp_utc"],
        "platform": release_readiness["platform"],
        "completion_status": _completion_status(release_readiness),
        "release_readiness_status": release_readiness["release_readiness_status"],
        "acceptance_status": release_readiness["acceptance_status"],
        "decision": release_readiness["decision"],
        "evidence_consistency_status": release_readiness["evidence_consistency_status"],
        "operator_validation_ready": release_readiness["operator_validation_ready"],
        "safe_to_run_without_ai": release_readiness["safe_to_run_without_ai"],
        "blocking_failures": release_readiness["blocking_failures"],
        "degraded_capabilities": release_readiness["degraded_capabilities"],
        "required_operator_checks": release_readiness["required_operator_checks"],
        "final_operator_summary": _final_operator_summary(release_readiness),
        "next_recommended_step": _next_recommended_step(release_readiness),
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_completion_report(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    release_readiness = build_platform_journey_release_readiness(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_completion_report_from_release_readiness(release_readiness)
