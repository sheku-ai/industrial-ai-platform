"""Platform product journey builder.

This module composes the existing diagnostics surface into a deterministic
end-to-end product journey. It does not introduce a new runtime subsystem and
it does not execute migrations, destructive actions, AI calls, vector calls or
long-running validations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.platform_diagnostics import (
    build_platform_diagnostics,
    build_platform_diagnostics_catalog,
)

JOURNEY_SCHEMA_VERSION = "1"


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _step_status(*, ready: bool, blocking: bool, degraded: bool = False) -> str:
    if ready and not degraded:
        return "ready"
    if degraded and not blocking:
        return "degraded"
    if not ready and blocking:
        return "blocked"
    return "degraded"


def _service_status(ready: bool) -> str:
    return "ready" if ready else "unavailable"


def _step(
    *,
    sequence: int,
    name: str,
    status: str,
    blocking: bool,
    description: str,
    evidence_keys: list[str],
    next_step: str | None = None,
    required_for: list[str] | None = None,
    optional_for: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "name": name,
        "status": status,
        "blocking": blocking,
        "description": description,
        "evidence_keys": evidence_keys,
        "required_for": required_for or [],
        "optional_for": optional_for or [],
        "next_step": next_step,
    }


def _build_summary_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": "platform_diagnostics_summary",
        "platform": diagnostics["platform"],
        "overall_status": diagnostics["overall_status"],
        "critical_services": {
            name: {
                "ready": service["ready"],
                "status": service["status"],
            }
            for name, service in diagnostics["critical_services"].items()
        },
        "optional_services": {
            name: {
                "ready": service["ready"],
                "status": service["status"],
                "blocking": service["blocking"],
            }
            for name, service in diagnostics["optional_services"].items()
        },
        "degraded_capabilities": diagnostics["degraded_capabilities"],
        "runtime_profiles": {
            name: {
                "ready": profile["ready"],
                "blocking": profile["blocking"],
            }
            for name, profile in diagnostics["runtime_profiles"].items()
        },
        "lifecycle_readiness": diagnostics["lifecycle_readiness"],
        "migrations": {
            "current_revision": diagnostics["migrations"]["current_revision"],
            "repository_head": diagnostics["migrations"]["repository_head"],
            "startup_compatible": diagnostics["migrations"]["startup_compatible"],
            "migration_required": diagnostics["migrations"]["migration_required"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def _build_issues_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for name, service in diagnostics["critical_services"].items():
        if not service["ready"]:
            issues.append(
                {
                    "code": f"critical_service_unavailable:{name}",
                    "severity": "critical",
                    "scope": "critical_services",
                    "name": name,
                    "message": f"Critical service {name} is not ready.",
                }
            )
    for capability in diagnostics["degraded_capabilities"]:
        issues.append(
            {
                "code": f"capability_degraded:{capability}",
                "severity": "degraded",
                "scope": "degraded_capabilities",
                "name": capability,
                "message": f"Optional capability {capability} is degraded.",
            }
        )
    for name, service in diagnostics["optional_services"].items():
        if not service["ready"]:
            issues.append(
                {
                    "code": f"optional_service_unavailable:{name}",
                    "severity": "degraded",
                    "scope": "optional_services",
                    "name": name,
                    "message": f"Optional service {name} is not ready.",
                }
            )

    issues = sorted(issues, key=lambda item: (item["severity"], item["scope"], item["name"], item["code"]))
    return {
        "plan": "platform_diagnostics_issues",
        "overall_status": diagnostics["overall_status"],
        "issue_count": len(issues),
        "issues": issues,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def _remediation_for_issue(issue: dict[str, Any]) -> dict[str, Any]:
    name = str(issue["name"])
    scope = str(issue["scope"])
    if scope == "critical_services" and name == "postgresql":
        action = "restore_postgresql_connectivity"
        command = "python scripts/platform_diagnostics.py --issues"
    elif scope == "critical_services" and name == "alembic":
        action = "restore_alembic_compatibility"
        command = "python scripts/platform_lifecycle.py status"
    elif scope == "critical_services" and name == "object_storage":
        action = "configure_object_storage"
        command = "python scripts/platform_lifecycle.py install-check"
    elif scope == "critical_services" and name == "secret_store":
        action = "configure_secret_store"
        command = "python scripts/platform_diagnostics.py --issues"
    elif scope == "optional_services" and name == "vector_store":
        action = "configure_optional_vector_store"
        command = "python scripts/platform_diagnostics.py --summary"
    elif scope == "optional_services" and name == "ai_provider":
        action = "configure_optional_ai_provider"
        command = "python scripts/platform_diagnostics.py --summary"
    elif scope == "degraded_capabilities":
        action = f"restore_optional_capability:{name}"
        command = "python scripts/platform_diagnostics.py --summary"
    else:
        action = "inspect_diagnostics"
        command = "python scripts/platform_diagnostics.py"
    return {
        "issue_code": issue["code"],
        "severity": issue["severity"],
        "action": action,
        "safe_to_automate": False,
        "destructive": False,
        "verification_command": command,
    }


def _build_remediation_from_issues(issues: dict[str, Any]) -> dict[str, Any]:
    remediation = [_remediation_for_issue(issue) for issue in issues["issues"]]
    return {
        "plan": "platform_diagnostics_remediation",
        "overall_status": issues["overall_status"],
        "remediation_count": len(remediation),
        "remediation": remediation,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Build the product journey from an existing diagnostics payload."""

    summary = _build_summary_from_diagnostics(diagnostics)
    issues = _build_issues_from_diagnostics(diagnostics)
    remediation = _build_remediation_from_issues(issues)
    catalog = build_platform_diagnostics_catalog()

    profiles = diagnostics["runtime_profiles"]
    core_profile = profiles["core"]
    document_profile = profiles["document_management"]
    ai_profile = profiles["ai_services"]
    degraded_capabilities = list(diagnostics["degraded_capabilities"])

    core_ready = bool(core_profile["ready"])
    document_ready = bool(document_profile["ready"])
    ai_ready = bool(ai_profile["ready"])
    ai_degraded = bool(degraded_capabilities or not ai_ready)
    platform_journey_complete = bool(core_ready and document_ready)
    blocking_issue_count = sum(1 for issue in issues["issues"] if issue.get("severity") == "critical")

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
            status=_step_status(
                ready=bool(diagnostics["lifecycle_readiness"]["ready"]),
                blocking=True,
            ),
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

    if platform_journey_complete and ai_degraded:
        journey_status = "complete_with_optional_degradation"
    elif platform_journey_complete:
        journey_status = "complete"
    else:
        journey_status = "blocked"

    return {
        "plan": "platform_product_journey",
        "journey_schema_version": JOURNEY_SCHEMA_VERSION,
        "timestamp_utc": utc_timestamp(),
        "platform": diagnostics["platform"],
        "journey_status": journey_status,
        "journey_complete": platform_journey_complete,
        "safe_to_run_without_ai": platform_journey_complete,
        "ai_services_blocking": False,
        "blocking_issue_count": blocking_issue_count,
        "degraded_capabilities": degraded_capabilities,
        "runtime_profiles": profiles,
        "steps": steps,
        "evidence": {
            "source": "live_platform_diagnostics",
            "summary": summary,
            "issues": issues,
            "remediation": remediation,
            "catalog": catalog,
        },
        "operator_next_actions": remediation["remediation"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
) -> dict[str, Any]:
    """Build the complete platform product journey from existing diagnostics."""

    diagnostics = build_platform_diagnostics(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    return build_platform_journey_from_diagnostics(diagnostics)
