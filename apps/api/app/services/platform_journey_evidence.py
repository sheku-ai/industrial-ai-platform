"""Build platform journey projections from diagnostics evidence snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.platform_journey import JOURNEY_SCHEMA_VERSION, _step, _step_status, utc_timestamp


def _mapping(payload: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{context}_missing_mapping:{key}")
    return value


def build_platform_journey_from_diagnostics_evidence(
    diagnostics_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a Sprint 29 diagnostics evidence snapshot into Sprint 30 journey form."""

    diagnostics = _mapping(diagnostics_evidence, "diagnostics", "diagnostics_evidence")
    summary = _mapping(diagnostics_evidence, "summary", "diagnostics_evidence")
    issues = _mapping(diagnostics_evidence, "issues", "diagnostics_evidence")
    remediation = _mapping(diagnostics_evidence, "remediation", "diagnostics_evidence")
    catalog = _mapping(diagnostics_evidence, "catalog", "diagnostics_evidence")
    profiles = _mapping(diagnostics, "runtime_profiles", "diagnostics")
    core_profile = _mapping(profiles, "core", "runtime_profiles")
    document_profile = _mapping(profiles, "document_management", "runtime_profiles")
    ai_profile = _mapping(profiles, "ai_services", "runtime_profiles")
    lifecycle = _mapping(diagnostics, "lifecycle_readiness", "diagnostics")

    degraded_capabilities = list(diagnostics.get("degraded_capabilities") or [])
    issue_items = list(issues.get("issues") or [])
    remediation_items = list(remediation.get("remediation") or [])

    core_ready = bool(core_profile.get("ready"))
    document_ready = bool(document_profile.get("ready"))
    ai_ready = bool(ai_profile.get("ready"))
    ai_degraded = bool(degraded_capabilities or not ai_ready)
    journey_complete = bool(core_ready and document_ready)
    blocking_issue_count = sum(1 for issue in issue_items if issue.get("severity") == "critical")

    steps = [
        _step(
            sequence=1,
            name="platform_identity",
            status="ready",
            blocking=True,
            description="Resolve generic platform metadata and release identity.",
            evidence_keys=["platform"],
            next_step="lifecycle_readiness",
            required_for=["core"],
        ),
        _step(
            sequence=2,
            name="lifecycle_readiness",
            status=_step_status(ready=bool(lifecycle.get("ready")), blocking=True),
            blocking=True,
            description="Confirm database lifecycle compatibility without executing migrations.",
            evidence_keys=["migrations", "lifecycle_readiness"],
            next_step="core_runtime",
            required_for=["core"],
        ),
        _step(
            sequence=3,
            name="core_runtime",
            status=_step_status(ready=core_ready, blocking=True),
            blocking=True,
            description="Confirm the core runtime profile required by the platform foundation.",
            evidence_keys=["runtime_profiles.core", "critical_services.postgresql", "critical_services.alembic"],
            next_step="document_management_runtime",
            required_for=["document_management"],
        ),
        _step(
            sequence=4,
            name="document_management_runtime",
            status=_step_status(ready=document_ready, blocking=True),
            blocking=True,
            description="Confirm document-management dependencies independent from AI services.",
            evidence_keys=["runtime_profiles.document_management", "critical_services.object_storage"],
            next_step="optional_ai_services",
            required_for=["document_management"],
        ),
        _step(
            sequence=5,
            name="optional_ai_services",
            status=_step_status(ready=ai_ready, blocking=False, degraded=ai_degraded),
            blocking=False,
            description="Report AI, vector and assistant capabilities as optional service-layer dependencies.",
            evidence_keys=["runtime_profiles.ai_services", "optional_services", "degraded_capabilities"],
            next_step="diagnostics_evidence",
            optional_for=["rag", "ai_assistants", "vector_search"],
        ),
        _step(
            sequence=6,
            name="diagnostics_evidence",
            status="ready",
            blocking=False,
            description="Use diagnostics output as non-destructive operator evidence for the journey.",
            evidence_keys=["summary", "issues", "remediation", "catalog"],
            next_step="operator_handoff",
        ),
        _step(
            sequence=7,
            name="operator_handoff",
            status="ready" if blocking_issue_count == 0 else "blocked",
            blocking=bool(blocking_issue_count),
            description="Expose unresolved blocking issues and non-automated remediation actions.",
            evidence_keys=["issues", "remediation"],
        ),
    ]

    if journey_complete and ai_degraded:
        journey_status = "complete_with_optional_degradation"
    elif journey_complete:
        journey_status = "complete"
    else:
        journey_status = "blocked"

    return {
        "plan": "platform_product_journey",
        "journey_schema_version": JOURNEY_SCHEMA_VERSION,
        "timestamp_utc": str(diagnostics_evidence.get("timestamp_utc") or utc_timestamp()),
        "platform": diagnostics.get("platform") or diagnostics_evidence.get("platform") or {},
        "journey_status": journey_status,
        "journey_complete": journey_complete,
        "safe_to_run_without_ai": journey_complete,
        "ai_services_blocking": False,
        "blocking_issue_count": blocking_issue_count,
        "degraded_capabilities": degraded_capabilities,
        "runtime_profiles": dict(profiles),
        "steps": steps,
        "evidence": {
            "source": "diagnostics_evidence_snapshot",
            "summary": dict(summary),
            "issues": dict(issues),
            "remediation": dict(remediation),
            "catalog": dict(catalog),
        },
        "operator_next_actions": remediation_items,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }
