"""Closeout package for the complete platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_projection import build_platform_journey_terminal_projections

CLOSEOUT_PACKAGE_SCHEMA_VERSION = "1"


def _closeout_status(completion_report: dict[str, Any]) -> str:
    status = completion_report["completion_status"]
    if status == "complete":
        return "ready_for_closeout"
    if status == "complete_with_optional_degradation":
        return "ready_for_closeout_with_optional_degradation"
    return "blocked"


def build_platform_journey_closeout_package_from_projections(
    projections: dict[str, Any],
) -> dict[str, Any]:
    """Build an operator closeout package from terminal projections."""

    handoff = projections["handoff"]
    operator_console = projections["operator_console"]
    release_readiness = projections["release_readiness"]
    completion_report = projections["completion_report"]
    bundle = projections["bundle"]
    evidence_store = bundle["evidence_store"]
    return {
        "plan": "platform_product_journey_closeout_package",
        "closeout_package_schema_version": CLOSEOUT_PACKAGE_SCHEMA_VERSION,
        "timestamp_utc": completion_report["timestamp_utc"],
        "platform": completion_report["platform"],
        "closeout_status": _closeout_status(completion_report),
        "completion_status": completion_report["completion_status"],
        "release_readiness_status": completion_report["release_readiness_status"],
        "acceptance_status": completion_report["acceptance_status"],
        "decision": completion_report["decision"],
        "safe_to_run_without_ai": completion_report["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "evidence_consistency_status": completion_report["evidence_consistency_status"],
        "blocking_failures": completion_report["blocking_failures"],
        "degraded_capabilities": completion_report["degraded_capabilities"],
        "next_recommended_step": completion_report["next_recommended_step"],
        "operator": {
            "ready_for_operator_validation": completion_report["operator_validation_ready"],
            "primary_action": operator_console["primary_action"],
            "required_check_count": len(completion_report["required_operator_checks"]),
            "command_count": len(handoff["operator_commands"]),
            "route_count": len(handoff["operator_routes"]),
        },
        "required_operator_checks": completion_report["required_operator_checks"],
        "operator_commands": handoff["operator_commands"],
        "operator_routes": handoff["operator_routes"],
        "evidence": {
            "index": evidence_store["index"],
            "latest": evidence_store["latest"],
            "consistency": evidence_store["consistency"],
        },
        "release_readiness": release_readiness,
        "completion_report": completion_report,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_closeout_package(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    projections = build_platform_journey_terminal_projections(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_closeout_package_from_projections(projections)
