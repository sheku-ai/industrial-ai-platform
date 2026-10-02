"""Operator handoff for the complete platform product journey.

The handoff is the final operator-facing projection of the Sprint 30 journey.
It derives all readiness and evidence from the existing journey bundle instead
of recalculating diagnostics or introducing new runtime checks.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_journey_bundle import build_platform_journey_bundle

HANDOFF_SCHEMA_VERSION = "1"


def _profile_ready(journey: dict[str, Any], profile_name: str) -> bool:
    profile = journey.get("runtime_profiles", {}).get(profile_name, {})
    return bool(profile.get("ready"))


def _service_ready(journey: dict[str, Any], service_group: str, service_name: str) -> bool:
    summary = journey.get("evidence", {}).get("summary", {})
    service = summary.get(service_group, {}).get(service_name, {})
    return bool(service.get("ready"))


def _gate(
    *,
    name: str,
    ready: bool,
    blocking: bool,
    evidence_keys: list[str],
    description: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "ready": ready,
        "status": "ready" if ready else ("blocked" if blocking else "degraded"),
        "blocking": blocking,
        "description": description,
        "evidence_keys": evidence_keys,
    }


def _operator_commands() -> list[dict[str, Any]]:
    return [
        {
            "name": "inspect_full_journey",
            "command": "python scripts/platform_journey.py",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_journey_summary",
            "command": "python scripts/platform_journey.py --summary",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_journey_actions",
            "command": "python scripts/platform_journey.py --actions",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_handoff",
            "command": "python scripts/platform_journey.py --handoff",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_bundle",
            "command": "python scripts/platform_journey.py --bundle",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "write_journey_evidence",
            "command": "python scripts/platform_journey.py --write-evidence",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_operator_console",
            "command": "python scripts/platform_journey.py --operator-console",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_readiness_matrix",
            "command": "python scripts/platform_journey.py --readiness-matrix",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_validation_plan",
            "command": "python scripts/platform_journey.py --validation-plan",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_acceptance",
            "command": "python scripts/platform_journey.py --acceptance",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_release_readiness",
            "command": "python scripts/platform_journey.py --release-readiness",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_completion_report",
            "command": "python scripts/platform_journey.py --completion-report",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_closeout_package",
            "command": "python scripts/platform_journey.py --closeout-package",
            "destructive": False,
            "executes_migrations": False,
        },
        {
            "name": "inspect_closeout_checklist",
            "command": "python scripts/platform_journey.py --closeout-checklist",
            "destructive": False,
            "executes_migrations": False,
        },
    ]


def _operator_routes() -> list[dict[str, Any]]:
    return [
        {"name": "full_journey", "method": "GET", "path": "/api/platform/journey"},
        {"name": "journey_summary", "method": "GET", "path": "/api/platform/journey/summary"},
        {"name": "journey_steps", "method": "GET", "path": "/api/platform/journey/steps"},
        {"name": "journey_actions", "method": "GET", "path": "/api/platform/journey/actions"},
        {"name": "journey_evidence_index", "method": "GET", "path": "/api/platform/journey/evidence"},
        {"name": "latest_journey_evidence", "method": "GET", "path": "/api/platform/journey/evidence/latest"},
        {"name": "journey_bundle", "method": "GET", "path": "/api/platform/journey/bundle"},
        {"name": "journey_handoff", "method": "GET", "path": "/api/platform/journey/handoff"},
        {"name": "operator_console", "method": "GET", "path": "/api/platform/journey/operator-console"},
        {"name": "readiness_matrix", "method": "GET", "path": "/api/platform/journey/readiness-matrix"},
        {"name": "validation_plan", "method": "GET", "path": "/api/platform/journey/validation-plan"},
        {"name": "acceptance", "method": "GET", "path": "/api/platform/journey/acceptance"},
        {"name": "release_readiness", "method": "GET", "path": "/api/platform/journey/release-readiness"},
        {"name": "completion_report", "method": "GET", "path": "/api/platform/journey/completion-report"},
        {"name": "closeout_package", "method": "GET", "path": "/api/platform/journey/closeout-package"},
        {"name": "closeout_checklist", "method": "GET", "path": "/api/platform/journey/closeout-checklist"},
    ]


def build_platform_journey_handoff_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build the final operator handoff from an existing journey bundle."""

    journey = bundle["journey"]
    summary = bundle["views"]["summary"]
    actions = bundle["views"]["actions"]
    evidence_store = bundle["evidence_store"]
    latest_evidence = evidence_store["latest"]
    evidence_consistency = evidence_store.get("consistency", {})

    core_ready = _profile_ready(journey, "core")
    document_ready = _profile_ready(journey, "document_management")
    ai_ready = _profile_ready(journey, "ai_services")
    object_storage_ready = _service_ready(journey, "critical_services", "object_storage")
    postgresql_ready = _service_ready(journey, "critical_services", "postgresql")
    alembic_ready = _service_ready(journey, "critical_services", "alembic")
    secret_store_ready = _service_ready(journey, "critical_services", "secret_store")

    gates = [
        _gate(
            name="core_platform",
            ready=core_ready,
            blocking=True,
            evidence_keys=["runtime_profiles.core", "critical_services.postgresql", "critical_services.alembic"],
            description="Core platform profile required for the product journey.",
        ),
        _gate(
            name="database_lifecycle",
            ready=bool(postgresql_ready and alembic_ready),
            blocking=True,
            evidence_keys=["critical_services.postgresql", "critical_services.alembic", "lifecycle_readiness"],
            description="PostgreSQL and Alembic compatibility required before operator handoff.",
        ),
        _gate(
            name="document_management",
            ready=document_ready,
            blocking=True,
            evidence_keys=["runtime_profiles.document_management", "critical_services.object_storage"],
            description="Document management readiness required for the E2E product journey.",
        ),
        _gate(
            name="object_storage",
            ready=object_storage_ready,
            blocking=True,
            evidence_keys=["critical_services.object_storage"],
            description="Object storage is required for document binaries, versions and artifacts.",
        ),
        _gate(
            name="secret_store",
            ready=secret_store_ready,
            blocking=True,
            evidence_keys=["critical_services.secret_store"],
            description="Secret store readiness required for operational configuration safety.",
        ),
        _gate(
            name="ai_services",
            ready=ai_ready,
            blocking=False,
            evidence_keys=["runtime_profiles.ai_services", "optional_services", "degraded_capabilities"],
            description="AI, vector and assistant capabilities are optional service-layer capabilities.",
        ),
        _gate(
            name="journey_evidence",
            ready=bool(latest_evidence.get("found")),
            blocking=False,
            evidence_keys=["evidence_store.latest", "evidence_store.index"],
            description="Stored journey evidence is recommended for audit handoff and manual validation.",
        ),
    ]

    blocking_gates = [gate["name"] for gate in gates if gate["blocking"] and not gate["ready"]]
    degraded_gates = [gate["name"] for gate in gates if not gate["blocking"] and not gate["ready"]]
    ready_for_operator_validation = bool(not blocking_gates and journey["journey_complete"])
    decision = "proceed" if ready_for_operator_validation else "hold"

    return {
        "plan": "platform_product_journey_handoff",
        "handoff_schema_version": HANDOFF_SCHEMA_VERSION,
        "timestamp_utc": bundle["timestamp_utc"],
        "platform": bundle["platform"],
        "journey_status": bundle["journey_status"],
        "journey_complete": bundle["journey_complete"],
        "decision": decision,
        "ready_for_operator_validation": ready_for_operator_validation,
        "safe_to_run_without_ai": bundle["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "blocking_gates": blocking_gates,
        "degraded_gates": degraded_gates,
        "degraded_capabilities": list(bundle["degraded_capabilities"]),
        "readiness_gates": gates,
        "operator_context": {
            "blocking_issue_count": bundle["blocking_issue_count"],
            "operator_next_action_count": summary["operator_next_action_count"],
            "evidence_available": bool(latest_evidence.get("found")),
            "evidence_consistency_status": evidence_consistency.get("status", "unknown"),
            "latest_evidence_timestamp_utc": bundle["operator"]["latest_evidence_timestamp_utc"],
        },
        "operator_next_actions": actions["actions"],
        "operator_commands": _operator_commands(),
        "operator_routes": _operator_routes(),
        "evidence": {
            "summary": summary,
            "actions": actions,
            "latest": latest_evidence,
            "consistency": evidence_consistency,
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_handoff(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Build the operator handoff from the existing platform journey bundle."""

    bundle = build_platform_journey_bundle(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_platform_journey_handoff_from_bundle(bundle)
