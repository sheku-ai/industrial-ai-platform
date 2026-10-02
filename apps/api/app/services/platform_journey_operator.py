"""Operator-facing projections for the complete platform product journey.

These views are derived from the platform journey handoff. They keep API/UI
consumers focused on operational decisions without introducing another source
of readiness truth.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_handoff import build_platform_journey_handoff

OPERATOR_CONSOLE_SCHEMA_VERSION = "1"
READINESS_MATRIX_SCHEMA_VERSION = "1"


def _status_rank(status: str) -> int:
    ranks = {"blocked": 0, "degraded": 1, "ready": 2}
    return ranks.get(status, 1)


def _gate_action(gate: dict[str, Any]) -> str:
    if gate["ready"]:
        return "none"
    if gate["blocking"]:
        return f"resolve_gate:{gate['name']}"
    return f"review_optional_gate:{gate['name']}"


def build_platform_journey_readiness_matrix_from_handoff(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic readiness matrix from the operator handoff."""

    rows = [
        {
            "name": gate["name"],
            "status": gate["status"],
            "ready": gate["ready"],
            "blocking": gate["blocking"],
            "required_for_proceed": bool(gate["blocking"]),
            "action_required": not gate["ready"],
            "operator_action": _gate_action(gate),
            "evidence_keys": gate["evidence_keys"],
            "description": gate["description"],
        }
        for gate in handoff["readiness_gates"]
    ]
    rows = sorted(rows, key=lambda row: (row["blocking"] is False, _status_rank(row["status"]), row["name"]))
    blocking_rows = [row for row in rows if row["blocking"] and not row["ready"]]
    degraded_rows = [row for row in rows if not row["blocking"] and not row["ready"]]

    return {
        "plan": "platform_product_journey_readiness_matrix",
        "readiness_matrix_schema_version": READINESS_MATRIX_SCHEMA_VERSION,
        "timestamp_utc": handoff["timestamp_utc"],
        "platform": handoff["platform"],
        "journey_status": handoff["journey_status"],
        "decision": handoff["decision"],
        "ready_for_operator_validation": handoff["ready_for_operator_validation"],
        "safe_to_run_without_ai": handoff["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "row_count": len(rows),
        "blocking_row_count": len(blocking_rows),
        "degraded_row_count": len(degraded_rows),
        "rows": rows,
        "degraded_capabilities": handoff["degraded_capabilities"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_operator_console_from_handoff(
    handoff: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact operator-console projection from the handoff."""

    matrix = build_platform_journey_readiness_matrix_from_handoff(handoff)
    blocking = [row for row in matrix["rows"] if row["blocking"] and not row["ready"]]
    degraded = [row for row in matrix["rows"] if not row["blocking"] and not row["ready"]]
    primary_action = (
        blocking[0]["operator_action"]
        if blocking
        else ("write_journey_evidence" if not handoff["operator_context"]["evidence_available"] else "monitor")
    )

    return {
        "plan": "platform_product_journey_operator_console",
        "operator_console_schema_version": OPERATOR_CONSOLE_SCHEMA_VERSION,
        "timestamp_utc": handoff["timestamp_utc"],
        "platform": handoff["platform"],
        "status": {
            "journey_status": handoff["journey_status"],
            "decision": handoff["decision"],
            "ready_for_operator_validation": handoff["ready_for_operator_validation"],
            "safe_to_run_without_ai": handoff["safe_to_run_without_ai"],
            "ai_services_blocking": False,
            "blocking_gate_count": len(blocking),
            "degraded_gate_count": len(degraded),
            "degraded_capabilities": handoff["degraded_capabilities"],
        },
        "primary_action": {
            "name": primary_action,
            "blocking": bool(blocking),
            "safe_to_automate": False,
            "destructive": False,
            "executes_migrations": False,
        },
        "readiness": {
            "blocking_gates": blocking,
            "degraded_gates": degraded,
            "matrix": matrix,
        },
        "evidence": {
            "available": handoff["operator_context"]["evidence_available"],
            "consistency_status": handoff["operator_context"]["evidence_consistency_status"],
            "latest_timestamp_utc": handoff["operator_context"]["latest_evidence_timestamp_utc"],
        },
        "actions": handoff["operator_next_actions"],
        "commands": handoff["operator_commands"],
        "routes": handoff["operator_routes"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_readiness_matrix(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    handoff = build_platform_journey_handoff(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_readiness_matrix_from_handoff(handoff)


def build_platform_journey_operator_console(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    handoff = build_platform_journey_handoff(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_operator_console_from_handoff(handoff)
