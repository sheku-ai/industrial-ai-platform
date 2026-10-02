"""Non-executing operator validation plan for the platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_operator import build_platform_journey_operator_console

VALIDATION_PLAN_SCHEMA_VERSION = "1"


def _command_by_name(console: dict[str, Any], name: str) -> dict[str, Any]:
    for command in console["commands"]:
        if command["name"] == name:
            return command
    return {"name": name, "command": "", "destructive": False, "executes_migrations": False}


def _route_by_name(console: dict[str, Any], name: str) -> dict[str, Any]:
    for route in console["routes"]:
        if route["name"] == name:
            return route
    return {"name": name, "method": "GET", "path": ""}


def _step(
    *,
    sequence: int,
    name: str,
    status: str,
    objective: str,
    command: dict[str, Any],
    route: dict[str, Any],
    expected_signal: str,
    blocking: bool,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "name": name,
        "status": status,
        "objective": objective,
        "command": command,
        "route": route,
        "expected_signal": expected_signal,
        "blocking": blocking,
        "destructive": False,
        "executes_migrations": False,
    }


def build_platform_journey_validation_plan_from_console(
    console: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic validation plan without executing checks."""

    status = console["status"]
    blocking = bool(status["blocking_gate_count"])
    degraded = bool(status["degraded_gate_count"] or status["degraded_capabilities"])
    plan_status = "blocked" if blocking else ("ready_with_optional_degradation" if degraded else "ready")

    steps = [
        _step(
            sequence=1,
            name="review_operator_console",
            status="ready",
            objective="Review the compact operator state and primary action.",
            command=_command_by_name(console, "inspect_operator_console"),
            route=_route_by_name(console, "operator_console"),
            expected_signal="plan=platform_product_journey_operator_console",
            blocking=False,
        ),
        _step(
            sequence=2,
            name="review_readiness_matrix",
            status="blocked" if blocking else "ready",
            objective="Confirm blocking gates before accepting the E2E journey.",
            command=_command_by_name(console, "inspect_readiness_matrix"),
            route=_route_by_name(console, "readiness_matrix"),
            expected_signal="blocking_row_count=0 for proceed",
            blocking=True,
        ),
        _step(
            sequence=3,
            name="review_operator_actions",
            status="blocked" if blocking else "ready",
            objective="Review non-automated remediation actions without executing them.",
            command=_command_by_name(console, "inspect_journey_actions"),
            route=_route_by_name(console, "journey_actions"),
            expected_signal="actions are non-destructive and safe_to_automate=false",
            blocking=blocking,
        ),
        _step(
            sequence=4,
            name="review_handoff_decision",
            status=status["decision"],
            objective="Confirm the handoff decision matches core and document-management readiness.",
            command=_command_by_name(console, "inspect_handoff"),
            route=_route_by_name(console, "journey_handoff"),
            expected_signal="decision=proceed when all blocking gates are ready",
            blocking=True,
        ),
        _step(
            sequence=5,
            name="capture_journey_evidence",
            status="ready" if console["evidence"]["available"] else "recommended",
            objective="Capture or refresh journey evidence for manual review and audit handoff.",
            command=_command_by_name(console, "write_journey_evidence"),
            route=_route_by_name(console, "latest_journey_evidence"),
            expected_signal="latest evidence exists and consistency is in_sync after capture",
            blocking=False,
        ),
    ]

    return {
        "plan": "platform_product_journey_validation_plan",
        "validation_plan_schema_version": VALIDATION_PLAN_SCHEMA_VERSION,
        "timestamp_utc": console["timestamp_utc"],
        "platform": console["platform"],
        "plan_status": plan_status,
        "decision": status["decision"],
        "ready_for_operator_validation": status["ready_for_operator_validation"],
        "safe_to_run_without_ai": status["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "blocking_gate_count": status["blocking_gate_count"],
        "degraded_gate_count": status["degraded_gate_count"],
        "degraded_capabilities": status["degraded_capabilities"],
        "evidence_consistency_status": console["evidence"]["consistency_status"],
        "step_count": len(steps),
        "steps": steps,
        "primary_action": console["primary_action"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_validation_plan(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    console = build_platform_journey_operator_console(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_validation_plan_from_console(console)
