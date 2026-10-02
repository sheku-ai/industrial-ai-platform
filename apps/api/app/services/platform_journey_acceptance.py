"""Operator acceptance projection for the platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_validation_plan import build_platform_journey_validation_plan

ACCEPTANCE_SCHEMA_VERSION = "1"


def _criterion(
    *,
    name: str,
    passed: bool,
    blocking: bool,
    evidence_key: str,
    description: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "status": "passed" if passed else ("failed" if blocking else "warning"),
        "blocking": blocking,
        "evidence_key": evidence_key,
        "description": description,
    }


def build_platform_journey_acceptance_from_validation_plan(
    validation_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic acceptance projection from the validation plan."""

    criteria = [
        _criterion(
            name="operator_validation_ready",
            passed=bool(validation_plan["ready_for_operator_validation"]),
            blocking=True,
            evidence_key="ready_for_operator_validation",
            description="Blocking readiness gates are clear for operator validation.",
        ),
        _criterion(
            name="core_and_document_journey_complete",
            passed=validation_plan["decision"] == "proceed",
            blocking=True,
            evidence_key="decision",
            description="Core platform and document-management profiles allow the journey to proceed.",
        ),
        _criterion(
            name="ai_services_non_blocking",
            passed=validation_plan["ai_services_blocking"] is False,
            blocking=True,
            evidence_key="ai_services_blocking",
            description="AI, vector, RAG and assistant capabilities do not block the platform journey.",
        ),
        _criterion(
            name="operator_plan_available",
            passed=bool(validation_plan["steps"]),
            blocking=True,
            evidence_key="steps",
            description="A non-executing operator validation plan is available.",
        ),
        _criterion(
            name="optional_degradation_reviewed",
            passed=validation_plan["degraded_gate_count"] == 0 and not validation_plan["degraded_capabilities"],
            blocking=False,
            evidence_key="degraded_capabilities",
            description="Optional degraded capabilities are visible and non-blocking.",
        ),
        _criterion(
            name="non_destructive_contract",
            passed=bool(
                validation_plan["destructive_action_executed"] is False
                and validation_plan["migration_executed"] is False
                and validation_plan["downgrade_executed"] is False
            ),
            blocking=True,
            evidence_key="destructive_action_executed",
            description="The journey projection does not execute destructive actions, migrations or downgrades.",
        ),
    ]
    blocking_failures = [
        criterion["name"] for criterion in criteria if criterion["blocking"] and not criterion["passed"]
    ]
    warnings = [criterion["name"] for criterion in criteria if not criterion["blocking"] and not criterion["passed"]]

    if blocking_failures:
        acceptance_status = "blocked"
    elif warnings:
        acceptance_status = "accepted_with_optional_degradation"
    else:
        acceptance_status = "accepted"

    return {
        "plan": "platform_product_journey_acceptance",
        "acceptance_schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "timestamp_utc": validation_plan["timestamp_utc"],
        "platform": validation_plan["platform"],
        "acceptance_status": acceptance_status,
        "decision": validation_plan["decision"],
        "ready_for_operator_validation": validation_plan["ready_for_operator_validation"],
        "safe_to_run_without_ai": validation_plan["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "criteria": criteria,
        "degraded_capabilities": validation_plan["degraded_capabilities"],
        "evidence_consistency_status": validation_plan["evidence_consistency_status"],
        "primary_action": validation_plan["primary_action"],
        "validation_plan": validation_plan,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_acceptance(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    validation_plan = build_platform_journey_validation_plan(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_acceptance_from_validation_plan(validation_plan)
