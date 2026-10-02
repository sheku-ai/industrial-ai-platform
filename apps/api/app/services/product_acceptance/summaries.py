from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.product_acceptance.gate_registry import MANDATORY_PHASES, get_gate_definition


def build_gate_summary(gates: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(gates),
        "mandatory": 0,
        "optional": 0,
        "passed": 0,
        "passed_with_warnings": 0,
        "failed": 0,
        "capability_missing": 0,
        "blocked_by_environment": 0,
        "skipped": 0,
        "mandatory_passed": 0,
        "mandatory_failed": 0,
        "mandatory_capability_missing": 0,
        "mandatory_blocked": 0,
        "mandatory_skipped": 0,
    }
    for gate in gates:
        status = str(gate.get("status", "")).lower()
        status_key = "blocked_by_environment" if status == "blocked_by_environment" else status
        if status_key in summary:
            summary[status_key] += 1
        mandatory = _is_mandatory(gate)
        summary["mandatory" if mandatory else "optional"] += 1
        if mandatory:
            if gate.get("status") == "PASSED":
                summary["mandatory_passed"] += 1
            elif gate.get("status") == "FAILED":
                summary["mandatory_failed"] += 1
            elif gate.get("status") == "CAPABILITY_MISSING":
                summary["mandatory_capability_missing"] += 1
            elif gate.get("status") == "BLOCKED_BY_ENVIRONMENT":
                summary["mandatory_blocked"] += 1
            elif gate.get("status") == "SKIPPED":
                summary["mandatory_skipped"] += 1
    return summary


def build_phase_summary(phases: list[dict[str, Any]], gates: list[dict[str, Any]]) -> dict[str, Any]:
    phase_items = build_phase_items(phases, gates)
    counts = {
        "total": len(phase_items),
        "executed": sum(1 for phase in phase_items if phase["executed"]),
        "passed": sum(1 for phase in phase_items if phase["status"] == "PASSED"),
        "failed": sum(1 for phase in phase_items if phase["status"] == "FAILED"),
        "capability_missing": sum(1 for phase in phase_items if phase["status"] == "CAPABILITY_MISSING"),
        "blocked_by_environment": sum(1 for phase in phase_items if phase["status"] == "BLOCKED_BY_ENVIRONMENT"),
        "skipped": sum(1 for phase in phase_items if phase["status"] == "SKIPPED"),
        "items": phase_items,
    }
    return counts


def build_phase_items(phases: list[dict[str, Any]], gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phase_by_code = {phase.get("phase_code"): phase for phase in phases}
    gate_phase_codes = {gate.get("phase_code") for gate in gates}
    all_phase_codes = sorted(set(phase_by_code) | gate_phase_codes | set(MANDATORY_PHASES))
    items: list[dict[str, Any]] = []
    for phase_code in all_phase_codes:
        phase = phase_by_code.get(phase_code, {})
        phase_gates = [gate for gate in gates if gate.get("phase_code") == phase_code]
        status = _phase_status(phase_gates, bool(phase), phase_code in MANDATORY_PHASES)
        warnings = [gate for gate in phase_gates if gate.get("status") == "PASSED_WITH_WARNINGS"]
        blockers = [
            gate
            for gate in phase_gates
            if gate.get("status") in {"FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT", "SKIPPED"}
            and _is_mandatory(gate)
        ]
        items.append(
            {
                "phase_code": phase_code,
                "status": status,
                "mandatory": phase_code in MANDATORY_PHASES,
                "executed": bool(phase),
                "started_at": phase.get("started_at"),
                "completed_at": phase.get("completed_at"),
                "duration_ms": _duration_ms(phase.get("started_at"), phase.get("completed_at")),
                "gate_count": len(phase_gates),
                "warnings": warnings,
                "blockers": blockers,
                "error_code": blockers[0].get("error_code") if blockers else None,
            }
        )
    return items


def _phase_status(phase_gates: list[dict[str, Any]], executed: bool, mandatory: bool) -> str:
    statuses = {gate.get("status") for gate in phase_gates}
    if not executed and mandatory:
        return "FAILED"
    if not phase_gates:
        return "SKIPPED" if not mandatory else "FAILED"
    for status in ("FAILED", "BLOCKED_BY_ENVIRONMENT", "CAPABILITY_MISSING", "PASSED_WITH_WARNINGS", "SKIPPED"):
        if status in statuses:
            return status
    return "PASSED"


def _is_mandatory(gate: dict[str, Any]) -> bool:
    definition = get_gate_definition(str(gate.get("phase_code")), str(gate.get("gate_code")))
    return definition.mandatory if definition else bool(gate.get("details", {}).get("mandatory"))


def _duration_ms(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        completed = datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return int((completed - started).total_seconds() * 1000)
