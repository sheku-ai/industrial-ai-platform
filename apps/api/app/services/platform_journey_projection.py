"""Shared terminal projections for the platform product journey."""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_acceptance import build_platform_journey_acceptance_from_validation_plan
from app.services.platform_journey_bundle import build_platform_journey_bundle
from app.services.platform_journey_completion_report import (
    build_platform_journey_completion_report_from_release_readiness,
)
from app.services.platform_journey_handoff import build_platform_journey_handoff_from_bundle
from app.services.platform_journey_operator import (
    build_platform_journey_operator_console_from_handoff,
    build_platform_journey_readiness_matrix_from_handoff,
)
from app.services.platform_journey_release_readiness import (
    build_platform_journey_release_readiness_from_acceptance,
)
from app.services.platform_journey_validation_plan import build_platform_journey_validation_plan_from_console

TERMINAL_PROJECTION_NAMES = {
    "bundle",
    "handoff",
    "operator_console",
    "readiness_matrix",
    "validation_plan",
    "acceptance",
    "release_readiness",
    "completion_report",
}


def build_platform_journey_terminal_projections(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Build all terminal journey projections from one bundle composition."""

    bundle = build_platform_journey_bundle(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    handoff = build_platform_journey_handoff_from_bundle(bundle)
    operator_console = build_platform_journey_operator_console_from_handoff(handoff)
    readiness_matrix = build_platform_journey_readiness_matrix_from_handoff(handoff)
    validation_plan = build_platform_journey_validation_plan_from_console(operator_console)
    acceptance = build_platform_journey_acceptance_from_validation_plan(validation_plan)
    release_readiness = build_platform_journey_release_readiness_from_acceptance(acceptance)
    completion_report = build_platform_journey_completion_report_from_release_readiness(release_readiness)
    return {
        "bundle": bundle,
        "handoff": handoff,
        "operator_console": operator_console,
        "readiness_matrix": readiness_matrix,
        "validation_plan": validation_plan,
        "acceptance": acceptance,
        "release_readiness": release_readiness,
        "completion_report": completion_report,
    }


def select_platform_journey_terminal_projection(
    name: str,
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Select one terminal journey projection from the shared composition."""

    if name not in TERMINAL_PROJECTION_NAMES:
        raise ValueError(f"unsupported_terminal_projection:{name}")
    projections = build_platform_journey_terminal_projections(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return projections[name]
