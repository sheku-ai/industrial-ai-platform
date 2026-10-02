"""Operator checklist derived from the platform journey closeout package."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_closeout import build_platform_journey_closeout_package

CLOSEOUT_CHECKLIST_SCHEMA_VERSION = "1"


def _check_status(item: dict[str, Any]) -> str:
    if item["blocking"] and item["status"] in {"blocked", "hold"}:
        return "blocked"
    if item["status"] in {"recommended", "degraded"}:
        return "recommended"
    return "ready"


def build_platform_journey_closeout_checklist_from_package(
    closeout_package: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact operator closeout checklist from the closeout package."""

    checklist = [
        {
            "sequence": check["sequence"],
            "name": check["name"],
            "status": _check_status(check),
            "blocking": check["blocking"],
            "command": check["command"],
            "route": check["route"],
            "expected_signal": check["expected_signal"],
            "destructive": False,
            "executes_migrations": False,
        }
        for check in closeout_package["required_operator_checks"]
    ]
    blocked = [item["name"] for item in checklist if item["blocking"] and item["status"] == "blocked"]
    recommended = [item["name"] for item in checklist if item["status"] == "recommended"]
    return {
        "plan": "platform_product_journey_closeout_checklist",
        "closeout_checklist_schema_version": CLOSEOUT_CHECKLIST_SCHEMA_VERSION,
        "timestamp_utc": closeout_package["timestamp_utc"],
        "platform": closeout_package["platform"],
        "closeout_status": closeout_package["closeout_status"],
        "completion_status": closeout_package["completion_status"],
        "decision": closeout_package["decision"],
        "safe_to_run_without_ai": closeout_package["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "evidence_consistency_status": closeout_package["evidence_consistency_status"],
        "blocked_check_count": len(blocked),
        "recommended_check_count": len(recommended),
        "blocked_checks": blocked,
        "recommended_checks": recommended,
        "check_count": len(checklist),
        "checklist": checklist,
        "next_recommended_step": closeout_package["next_recommended_step"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_closeout_checklist(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    closeout_package = build_platform_journey_closeout_package(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_closeout_checklist_from_package(closeout_package)
