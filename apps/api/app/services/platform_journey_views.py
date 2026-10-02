"""Lightweight views for the platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey import build_platform_journey


def _journey(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    return build_platform_journey(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )


def build_platform_journey_summary_from_journey(journey: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": "platform_product_journey_summary",
        "platform": journey["platform"],
        "journey_status": journey["journey_status"],
        "journey_complete": journey["journey_complete"],
        "safe_to_run_without_ai": journey["safe_to_run_without_ai"],
        "ai_services_blocking": journey["ai_services_blocking"],
        "blocking_issue_count": journey["blocking_issue_count"],
        "degraded_capabilities": journey["degraded_capabilities"],
        "step_count": len(journey["steps"]),
        "operator_next_action_count": len(journey["operator_next_actions"]),
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_steps_from_journey(journey: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": "platform_product_journey_steps",
        "journey_status": journey["journey_status"],
        "journey_complete": journey["journey_complete"],
        "steps": journey["steps"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_actions_from_journey(journey: dict[str, Any]) -> dict[str, Any]:
    actions = list(journey["operator_next_actions"])
    return {
        "plan": "platform_product_journey_actions",
        "journey_status": journey["journey_status"],
        "blocking_issue_count": journey["blocking_issue_count"],
        "action_count": len(actions),
        "actions": actions,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_summary(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    journey = _journey(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    return build_platform_journey_summary_from_journey(journey)


def build_platform_journey_steps(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    journey = _journey(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    return build_platform_journey_steps_from_journey(journey)


def build_platform_journey_actions(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    journey = _journey(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    return build_platform_journey_actions_from_journey(journey)
