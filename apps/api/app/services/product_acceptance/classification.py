from __future__ import annotations

from typing import Any

from app.services.product_acceptance.error_codes import error_payload
from app.services.product_acceptance.gate_registry import GATE_REGISTRY, MANDATORY_PHASES, get_gate_definition


def validate_gate_contract(
    gates: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    persisted_gates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    phase_codes = {phase.get("phase_code") for phase in phases}
    gate_keys = {(gate.get("phase_code"), gate.get("gate_code")) for gate in gates}

    for gate in gates:
        key = (gate.get("phase_code"), gate.get("gate_code"))
        definition = get_gate_definition(str(key[0]), str(key[1]))
        if key in seen:
            errors.append(_contract_error("duplicate_gate", gate))
        seen.add(key)
        if definition is None:
            errors.append(_contract_error("unknown_gate", gate))
            continue
        if gate.get("status") not in definition.allowed_statuses:
            errors.append(_contract_error("status_not_allowed", gate))
        if definition.mandatory and gate.get("status") == "SKIPPED":
            errors.append(_contract_error("mandatory_gate_skipped", gate))

    for definition in GATE_REGISTRY.values():
        if definition.mandatory and definition.key not in gate_keys:
            errors.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "contract_error": "mandatory_gate_missing",
                    "phase_code": definition.phase_code,
                    "gate_code": definition.gate_code,
                }
            )

    for phase_code in MANDATORY_PHASES:
        if phase_code not in phase_codes:
            errors.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "contract_error": "mandatory_phase_missing",
                    "phase_code": phase_code,
                }
            )
        elif not any(gate.get("phase_code") == phase_code for gate in gates):
            errors.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "contract_error": "mandatory_phase_without_gates",
                    "phase_code": phase_code,
                }
            )

    if persisted_gates is not None:
        persisted_keys = {(gate.get("phase_code"), gate.get("gate_code")) for gate in persisted_gates}
        for key in gate_keys - persisted_keys:
            errors.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "contract_error": "gate_in_report_not_persisted",
                    "phase_code": key[0],
                    "gate_code": key[1],
                }
            )
        for key in persisted_keys - gate_keys:
            errors.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "contract_error": "gate_persisted_not_in_report",
                    "phase_code": key[0],
                    "gate_code": key[1],
                }
            )

    return errors


def classify_global_status(
    gates: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    contract_errors: list[dict[str, Any]] | None = None,
) -> str:
    if contract_errors:
        return "FAILED"

    mandatory_gates = [gate for gate in gates if _is_mandatory(gate)]
    optional_gates = [gate for gate in gates if not _is_mandatory(gate)]

    if any(gate.get("status") == "FAILED" for gate in mandatory_gates):
        return "FAILED"
    if any(gate.get("status") == "SKIPPED" for gate in mandatory_gates):
        return "FAILED"
    if any(gate.get("status") == "FAILED" for gate in optional_gates):
        return "PASSED_WITH_WARNINGS"
    if any(gate.get("status") == "BLOCKED_BY_ENVIRONMENT" for gate in mandatory_gates):
        return "BLOCKED_BY_ENVIRONMENT"
    if any(gate.get("status") == "CAPABILITY_MISSING" for gate in mandatory_gates):
        return "FAILED"
    if any(gate.get("status") == "CAPABILITY_MISSING" for gate in optional_gates):
        return "PASSED_WITH_WARNINGS"
    if any(gate.get("status") == "PASSED_WITH_WARNINGS" for gate in gates):
        return "PASSED_WITH_WARNINGS"
    if warnings:
        return "PASSED_WITH_WARNINGS"
    return "PASSED"


def release_candidate_blockers(
    gates: list[dict[str, Any]],
    contract_errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for gate in gates:
        if not _is_mandatory(gate):
            continue
        if gate.get("status") in {"FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT", "SKIPPED"}:
            blockers.append(
                {
                    "phase_code": gate.get("phase_code"),
                    "gate_code": gate.get("gate_code"),
                    "status": gate.get("status"),
                    "error_code": gate.get("error_code") or "ACCEPTANCE_GATE_CONTRACT_INVALID",
                }
            )
    for error in contract_errors or []:
        blockers.append(
            {
                "phase_code": error.get("phase_code"),
                "gate_code": error.get("gate_code"),
                "status": "FAILED",
                "error_code": error.get("error_code"),
            }
        )
    return blockers


def is_release_candidate_eligible(
    final_status: str,
    gates: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    idempotency: dict[str, Any],
) -> bool:
    if final_status not in {"PASSED", "PASSED_WITH_WARNINGS"}:
        return False
    if blockers:
        return False
    if any(_is_mandatory(gate) and gate.get("status") != "PASSED" for gate in gates):
        return False
    if not idempotency.get("verified", False):
        return False
    return not idempotency.get("duplicate_assets_detected")

def cli_exit_code(
    report: dict[str, Any],
    invalid_args: bool = False,
    persistence_or_report_failed: bool = False,
) -> int:
    if invalid_args:
        return 2
    if persistence_or_report_failed:
        return 4
    status = report.get("final_status") or report.get("status")
    if status in {"PASSED", "PASSED_WITH_WARNINGS"} and report.get("release_candidate_eligible"):
        return 0
    if status == "BLOCKED_BY_ENVIRONMENT":
        return 3
    return 1


def _is_mandatory(gate: dict[str, Any]) -> bool:
    definition = get_gate_definition(str(gate.get("phase_code")), str(gate.get("gate_code")))
    if definition is not None:
        return definition.mandatory
    return bool(gate.get("mandatory", False) or gate.get("details", {}).get("mandatory", False))


def _contract_error(reason: str, gate: dict[str, Any]) -> dict[str, Any]:
    return {
        **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
        "contract_error": reason,
        "phase_code": gate.get("phase_code"),
        "gate_code": gate.get("gate_code"),
        "status": gate.get("status"),
    }
