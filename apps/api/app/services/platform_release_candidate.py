"""Release Candidate readiness projections for the platform.

This module composes existing diagnostics and Product Journey closeout outputs
into non-executing release candidate views. It does not run validations,
migrations, remediations or destructive operations.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_diagnostics import (
    build_platform_diagnostics_issues,
    build_platform_diagnostics_summary,
)
from app.services.platform_journey_closeout import build_platform_journey_closeout_package
from app.services.platform_journey_closeout_checklist import (
    build_platform_journey_closeout_checklist_from_package,
)

RELEASE_CANDIDATE_SCHEMA_VERSION = "1"
RELEASE_COMMAND_CATALOG_SCHEMA_VERSION = "1"
RELEASE_EVIDENCE_SCHEMA_VERSION = "1"
RELEASE_GATE_SCHEMA_VERSION = "1"
RELEASE_CHECKLIST_SCHEMA_VERSION = "1"
RELEASE_CI_CONTRACT_SCHEMA_VERSION = "1"
RELEASE_MANIFEST_SCHEMA_VERSION = "1"
RELEASE_METADATA_SCHEMA_VERSION = "1"
RELEASE_ARTIFACT_CATALOG_SCHEMA_VERSION = "1"
RELEASE_COMPATIBILITY_SCHEMA_VERSION = "1"
RELEASE_SUMMARY_SCHEMA_VERSION = "1"
RELEASE_CONTRACT_SCHEMA_VERSION = "1"


def _command(
    *,
    name: str,
    command: str,
    category: str,
    expected_signal: str,
    blocking: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "command": command,
        "expected_signal": expected_signal,
        "blocking": blocking,
        "destructive": False,
        "executes_migrations": False,
        "executes_remediation": False,
    }


def build_release_candidate_command_catalog() -> dict[str, Any]:
    """Build a deterministic catalog of manual RC validation commands."""

    commands = [
        _command(
            name="platform_diagnostics",
            category="diagnostics",
            command="python scripts/platform_diagnostics.py",
            expected_signal="plan=platform_diagnostics",
            blocking=True,
        ),
        _command(
            name="platform_diagnostics_summary",
            category="diagnostics",
            command="python scripts/platform_diagnostics.py --summary",
            expected_signal="critical services and runtime profiles are visible",
            blocking=True,
        ),
        _command(
            name="platform_diagnostics_issues",
            category="diagnostics",
            command="python scripts/platform_diagnostics.py --issues",
            expected_signal="critical issue count is zero for RC proceed",
            blocking=True,
        ),
        _command(
            name="platform_lifecycle_install_check",
            category="lifecycle",
            command="python scripts/platform_lifecycle.py install-check",
            expected_signal="document_management profile is ready",
            blocking=True,
        ),
        _command(
            name="platform_journey_closeout_package",
            category="journey",
            command="python scripts/platform_journey.py --closeout-package",
            expected_signal="closeout_status is ready or ready_with_optional_degradation",
            blocking=True,
        ),
        _command(
            name="platform_journey_closeout_checklist",
            category="journey",
            command="python scripts/platform_journey.py --closeout-checklist",
            expected_signal="blocked_check_count=0",
            blocking=True,
        ),
        _command(
            name="platform_journey_completion_report",
            category="journey",
            command="python scripts/platform_journey.py --completion-report",
            expected_signal="completion_status is complete or complete_with_optional_degradation",
            blocking=True,
        ),
        _command(
            name="platform_journey_release_readiness",
            category="journey",
            command="python scripts/platform_journey.py --release-readiness",
            expected_signal="release_readiness_status is ready or ready_with_optional_degradation",
            blocking=True,
        ),
        _command(
            name="platform_journey_evidence_write",
            category="evidence",
            command="python scripts/platform_journey.py --write-evidence",
            expected_signal="new journey evidence snapshot is written",
            blocking=False,
        ),
    ]
    return {
        "plan": "platform_release_candidate_command_catalog",
        "command_catalog_schema_version": RELEASE_COMMAND_CATALOG_SCHEMA_VERSION,
        "command_count": len(commands),
        "commands": commands,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def _diagnostics_ready(summary: dict[str, Any]) -> bool:
    profiles = summary["runtime_profiles"]
    return bool(profiles["core"]["ready"] and profiles["document_management"]["ready"])


def _critical_issue_count(issues: dict[str, Any]) -> int:
    return sum(1 for issue in issues["issues"] if issue.get("severity") == "critical")


def build_release_candidate_evidence(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Aggregate RC evidence from diagnostics and Product Journey closeout."""

    diagnostics_summary = build_platform_diagnostics_summary(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    diagnostics_issues = build_platform_diagnostics_issues(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    closeout_package = build_platform_journey_closeout_package(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    closeout_checklist = build_platform_journey_closeout_checklist_from_package(closeout_package)
    return {
        "plan": "platform_release_candidate_evidence",
        "release_evidence_schema_version": RELEASE_EVIDENCE_SCHEMA_VERSION,
        "platform": closeout_package["platform"],
        "diagnostics_ready": _diagnostics_ready(diagnostics_summary),
        "diagnostics_overall_status": diagnostics_summary["overall_status"],
        "diagnostics_issue_count": diagnostics_issues["issue_count"],
        "diagnostics_critical_issue_count": _critical_issue_count(diagnostics_issues),
        "closeout_status": closeout_package["closeout_status"],
        "completion_status": closeout_package["completion_status"],
        "release_readiness_status": closeout_package["release_readiness_status"],
        "evidence_consistency_status": closeout_package["evidence_consistency_status"],
        "safe_to_run_without_ai": closeout_package["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "degraded_capabilities": closeout_package["degraded_capabilities"],
        "blocking_failures": closeout_package["blocking_failures"],
        "diagnostics": {
            "summary": diagnostics_summary,
            "issues": diagnostics_issues,
        },
        "journey": {
            "closeout_package": closeout_package,
            "closeout_checklist": closeout_checklist,
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def _gate(
    *,
    name: str,
    ready: bool,
    blocking: bool,
    evidence_key: str,
    description: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "ready": ready,
        "status": "ready" if ready else ("blocked" if blocking else "degraded"),
        "blocking": blocking,
        "evidence_key": evidence_key,
        "description": description,
        "destructive": False,
        "executes_migrations": False,
        "executes_remediation": False,
    }


def build_release_candidate_gates_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Build non-destructive RC gates from aggregated evidence."""

    closeout = evidence["journey"]["closeout_package"]
    checklist = evidence["journey"]["closeout_checklist"]
    gates = [
        _gate(
            name="core_platform",
            ready=bool(evidence["diagnostics"]["summary"]["runtime_profiles"]["core"]["ready"]),
            blocking=True,
            evidence_key="diagnostics.summary.runtime_profiles.core",
            description="Core platform profile must be ready for RC.",
        ),
        _gate(
            name="document_management",
            ready=bool(evidence["diagnostics"]["summary"]["runtime_profiles"]["document_management"]["ready"]),
            blocking=True,
            evidence_key="diagnostics.summary.runtime_profiles.document_management",
            description="Document Management profile must be ready for RC.",
        ),
        _gate(
            name="diagnostics_critical_issues",
            ready=evidence["diagnostics_critical_issue_count"] == 0,
            blocking=True,
            evidence_key="diagnostics_critical_issue_count",
            description="Critical diagnostics issues must be resolved before RC.",
        ),
        _gate(
            name="journey_closeout",
            ready=closeout["closeout_status"]
            in {
                "ready_for_closeout",
                "ready_for_closeout_with_optional_degradation",
            },
            blocking=True,
            evidence_key="journey.closeout_package.closeout_status",
            description="Product Journey closeout must be ready for RC.",
        ),
        _gate(
            name="operator_checklist",
            ready=checklist["blocked_check_count"] == 0,
            blocking=True,
            evidence_key="journey.closeout_checklist.blocked_check_count",
            description="Blocking operator checks must be clear.",
        ),
        _gate(
            name="evidence_consistency",
            ready=evidence["evidence_consistency_status"] == "in_sync",
            blocking=False,
            evidence_key="journey.closeout_package.evidence_consistency_status",
            description="Stored Product Journey evidence should match live journey state.",
        ),
        _gate(
            name="optional_ai_services",
            ready=not evidence["degraded_capabilities"],
            blocking=False,
            evidence_key="degraded_capabilities",
            description="AI, vector, RAG and assistant degradations are visible but non-blocking.",
        ),
    ]
    blocking_failures = [gate["name"] for gate in gates if gate["blocking"] and not gate["ready"]]
    degraded_gates = [gate["name"] for gate in gates if not gate["blocking"] and not gate["ready"]]
    return {
        "plan": "platform_release_candidate_gates",
        "release_gate_schema_version": RELEASE_GATE_SCHEMA_VERSION,
        "gate_count": len(gates),
        "blocking_failure_count": len(blocking_failures),
        "degraded_gate_count": len(degraded_gates),
        "blocking_failures": blocking_failures,
        "degraded_gates": degraded_gates,
        "gates": gates,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


GATE_COMMAND_NAMES = {
    "core_platform": "platform_diagnostics_summary",
    "document_management": "platform_lifecycle_install_check",
    "diagnostics_critical_issues": "platform_diagnostics_issues",
    "journey_closeout": "platform_journey_closeout_package",
    "operator_checklist": "platform_journey_closeout_checklist",
    "evidence_consistency": "platform_journey_evidence_write",
    "optional_ai_services": "platform_journey_release_readiness",
}


def _command_by_name(commands: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for command in commands:
        if command["name"] == name:
            return command
    return {
        "name": name,
        "category": "unknown",
        "command": "",
        "expected_signal": "",
        "blocking": False,
        "destructive": False,
        "executes_migrations": False,
        "executes_remediation": False,
    }


def _check_from_gate(sequence: int, gate: dict[str, Any], commands: list[dict[str, Any]]) -> dict[str, Any]:
    command = _command_by_name(commands, GATE_COMMAND_NAMES.get(gate["name"], "platform_diagnostics"))
    return {
        "sequence": sequence,
        "name": gate["name"],
        "status": gate["status"],
        "blocking": gate["blocking"],
        "operator_action": "none" if gate["ready"] else f"review_gate:{gate['name']}",
        "command": command,
        "evidence_key": gate["evidence_key"],
        "destructive": False,
        "executes_migrations": False,
        "executes_remediation": False,
    }


def build_release_candidate_gates(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    evidence = build_release_candidate_evidence(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_release_candidate_gates_from_evidence(evidence)


def build_release_candidate_checklist_from_gates(
    gates: dict[str, Any],
    command_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Build an operator-facing RC checklist from release gates."""

    commands = list(command_catalog["commands"])
    checklist = [_check_from_gate(index, gate, commands) for index, gate in enumerate(gates["gates"], start=1)]
    blocked = [item["name"] for item in checklist if item["blocking"] and item["status"] == "blocked"]
    recommended = [item["name"] for item in checklist if not item["blocking"] and item["status"] != "ready"]
    return {
        "plan": "platform_release_candidate_checklist",
        "release_checklist_schema_version": RELEASE_CHECKLIST_SCHEMA_VERSION,
        "check_count": len(checklist),
        "blocked_check_count": len(blocked),
        "recommended_check_count": len(recommended),
        "blocked_checks": blocked,
        "recommended_checks": recommended,
        "checklist": checklist,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_candidate_checklist(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    evidence = build_release_candidate_evidence(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    gates = build_release_candidate_gates_from_evidence(evidence)
    command_catalog = build_release_candidate_command_catalog()
    return build_release_candidate_checklist_from_gates(gates, command_catalog)


def _release_candidate_status(gates: dict[str, Any]) -> str:
    if gates["blocking_failures"]:
        return "blocked"
    if gates["degraded_gates"]:
        return "ready_with_optional_degradation"
    return "ready"


def build_release_candidate_ci_contract_from_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    """Build a non-executing CI contract from RC readiness."""

    command_by_name = {command["name"]: command for command in readiness["command_catalog"]["commands"]}
    required_checks = [
        {
            "name": gate["name"],
            "status": gate["status"],
            "blocking": gate["blocking"],
            "command": command_by_name.get(
                GATE_COMMAND_NAMES.get(gate["name"], "platform_diagnostics"),
                {},
            ),
            "evidence_key": gate["evidence_key"],
            "expected_status": "ready",
            "destructive": False,
            "executes_migrations": False,
            "executes_remediation": False,
        }
        for gate in readiness["gates"]["gates"]
    ]
    blocking_checks = [check["name"] for check in required_checks if check["blocking"]]
    optional_checks = [check["name"] for check in required_checks if not check["blocking"]]
    return {
        "plan": "platform_release_candidate_ci_contract",
        "ci_contract_schema_version": RELEASE_CI_CONTRACT_SCHEMA_VERSION,
        "release_candidate_status": readiness["release_candidate_status"],
        "safe_to_run_without_ai": readiness["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "blocking_checks": blocking_checks,
        "optional_checks": optional_checks,
        "required_checks": required_checks,
        "manual_execution_required": True,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_candidate_ci_contract(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    readiness = build_release_candidate_readiness(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_release_candidate_ci_contract_from_readiness(readiness)


def build_release_candidate_manifest_from_readiness(
    readiness: dict[str, Any],
    ci_contract: dict[str, Any],
) -> dict[str, Any]:
    """Build the Release Candidate manifest from RC readiness and CI contract."""

    evidence = readiness["evidence"]
    diagnostics_summary = evidence["diagnostics"]["summary"]
    migrations = diagnostics_summary["migrations"]
    runtime_profiles = diagnostics_summary["runtime_profiles"]
    readiness_profiles = {
        "core": {
            "ready": bool(runtime_profiles["core"]["ready"]),
            "blocking": True,
        },
        "document_management": {
            "ready": bool(runtime_profiles["document_management"]["ready"]),
            "blocking": True,
        },
        "ai_services": {
            "ready": bool(runtime_profiles["ai_services"]["ready"]),
            "blocking": False,
        },
    }
    validation_commands = [
        {
            "name": command["name"],
            "category": command["category"],
            "command": command["command"],
            "blocking": command["blocking"],
            "expected_signal": command["expected_signal"],
            "destructive": False,
            "executes_migrations": False,
            "executes_remediation": False,
        }
        for command in readiness["command_catalog"]["commands"]
    ]
    blocking_gates = [gate["name"] for gate in readiness["gates"]["gates"] if gate["blocking"] and not gate["ready"]]
    optional_degradations = [
        gate["name"] for gate in readiness["gates"]["gates"] if not gate["blocking"] and not gate["ready"]
    ]
    return {
        "plan": "platform_release_candidate_manifest",
        "manifest_schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "platform": readiness["platform"],
        "release_candidate_status": readiness["release_candidate_status"],
        "release_stage": readiness["platform"].get("release_stage", "unknown"),
        "current_version": readiness["platform"].get("version", "unknown"),
        "migration_revision": migrations["current_revision"],
        "repository_head": migrations["repository_head"],
        "readiness_profiles": readiness_profiles,
        "blocking_gates": blocking_gates,
        "optional_degradations": optional_degradations,
        "validation_commands": validation_commands,
        "evidence_summary": {
            "diagnostics_ready": evidence["diagnostics_ready"],
            "diagnostics_overall_status": evidence["diagnostics_overall_status"],
            "diagnostics_issue_count": evidence["diagnostics_issue_count"],
            "diagnostics_critical_issue_count": evidence["diagnostics_critical_issue_count"],
            "closeout_status": evidence["closeout_status"],
            "completion_status": evidence["completion_status"],
            "release_readiness_status": evidence["release_readiness_status"],
            "evidence_consistency_status": evidence["evidence_consistency_status"],
            "safe_to_run_without_ai": evidence["safe_to_run_without_ai"],
            "degraded_capabilities": evidence["degraded_capabilities"],
        },
        "ci_contract_summary": {
            "plan": ci_contract["plan"],
            "release_candidate_status": ci_contract["release_candidate_status"],
            "blocking_check_count": len(ci_contract["blocking_checks"]),
            "optional_check_count": len(ci_contract["optional_checks"]),
            "required_check_count": len(ci_contract["required_checks"]),
            "manual_execution_required": ci_contract["manual_execution_required"],
        },
        "generated_from": {
            "readiness": readiness["plan"],
            "evidence": evidence["plan"],
            "gates": readiness["gates"]["plan"],
            "checklist": readiness["checklist"]["plan"],
            "command_catalog": readiness["command_catalog"]["plan"],
            "ci_contract": ci_contract["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_candidate_manifest(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    readiness = build_release_candidate_readiness(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    ci_contract = build_release_candidate_ci_contract_from_readiness(readiness)
    return build_release_candidate_manifest_from_readiness(readiness, ci_contract)


def build_release_metadata_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build release metadata from the RC manifest."""

    return {
        "plan": "platform_release_metadata",
        "release_metadata_schema_version": RELEASE_METADATA_SCHEMA_VERSION,
        "platform": manifest["platform"],
        "release_stage": manifest["release_stage"],
        "current_version": manifest["current_version"],
        "release_candidate_status": manifest["release_candidate_status"],
        "migration_revision": manifest["migration_revision"],
        "repository_head": manifest["repository_head"],
        "safe_to_run_without_ai": manifest["evidence_summary"]["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "generated_from": {
            "manifest": manifest["plan"],
            "readiness": manifest["generated_from"]["readiness"],
            "evidence": manifest["generated_from"]["evidence"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_artifact_catalog_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic release artifact catalog from RC manifest outputs."""

    artifact_specs = [
        ("diagnostics_summary", "diagnostics", "diagnostics summary evidence", True),
        ("diagnostics_issues", "diagnostics", "diagnostics issue evidence", True),
        ("lifecycle_install_check", "lifecycle", "installation readiness contract", True),
        ("journey_closeout_package", "journey", "Product Journey closeout package", True),
        ("journey_closeout_checklist", "journey", "operator closeout checklist", True),
        ("release_candidate_readiness", "release", "Release Candidate readiness payload", True),
        ("release_candidate_manifest", "release", "Release Candidate manifest", True),
        ("release_candidate_ci_contract", "ci", "non-executing CI contract", True),
        ("journey_evidence_snapshot", "evidence", "stored Product Journey evidence snapshot", False),
    ]
    artifacts = [
        {
            "name": name,
            "category": category,
            "description": description,
            "required_for_release_candidate": required,
            "blocking": required,
            "source": "generated_contract",
            "destructive": False,
            "executes_migrations": False,
            "executes_remediation": False,
        }
        for name, category, description, required in artifact_specs
    ]
    return {
        "plan": "platform_release_artifact_catalog",
        "artifact_catalog_schema_version": RELEASE_ARTIFACT_CATALOG_SCHEMA_VERSION,
        "release_candidate_status": manifest["release_candidate_status"],
        "artifact_count": len(artifacts),
        "required_artifact_count": sum(1 for artifact in artifacts if artifact["required_for_release_candidate"]),
        "artifacts": artifacts,
        "generated_from": {
            "manifest": manifest["plan"],
            "command_catalog": manifest["generated_from"]["command_catalog"],
            "ci_contract": manifest["generated_from"]["ci_contract"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_compatibility_matrix_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a release compatibility matrix from RC manifest state."""

    profiles = manifest["readiness_profiles"]
    evidence_summary = manifest["evidence_summary"]
    compatibility = [
        {
            "name": "core_platform",
            "compatible": bool(profiles["core"]["ready"]),
            "blocking": True,
            "required": True,
            "status": "compatible" if profiles["core"]["ready"] else "blocked",
            "evidence_key": "readiness_profiles.core",
        },
        {
            "name": "document_management",
            "compatible": bool(profiles["document_management"]["ready"]),
            "blocking": True,
            "required": True,
            "status": "compatible" if profiles["document_management"]["ready"] else "blocked",
            "evidence_key": "readiness_profiles.document_management",
        },
        {
            "name": "migration_state",
            "compatible": manifest["migration_revision"] == manifest["repository_head"],
            "blocking": True,
            "required": True,
            "status": "compatible" if manifest["migration_revision"] == manifest["repository_head"] else "blocked",
            "evidence_key": "migration_revision",
        },
        {
            "name": "product_journey_closeout",
            "compatible": evidence_summary["closeout_status"]
            in {
                "ready_for_closeout",
                "ready_for_closeout_with_optional_degradation",
            },
            "blocking": True,
            "required": True,
            "status": "compatible"
            if evidence_summary["closeout_status"]
            in {"ready_for_closeout", "ready_for_closeout_with_optional_degradation"}
            else "blocked",
            "evidence_key": "evidence_summary.closeout_status",
        },
        {
            "name": "ai_services",
            "compatible": bool(profiles["ai_services"]["ready"]),
            "blocking": False,
            "required": False,
            "status": "compatible" if profiles["ai_services"]["ready"] else "degraded",
            "evidence_key": "readiness_profiles.ai_services",
        },
        {
            "name": "journey_evidence_consistency",
            "compatible": evidence_summary["evidence_consistency_status"] == "in_sync",
            "blocking": False,
            "required": False,
            "status": "compatible" if evidence_summary["evidence_consistency_status"] == "in_sync" else "degraded",
            "evidence_key": "evidence_summary.evidence_consistency_status",
        },
    ]
    blocking_incompatibilities = [item["name"] for item in compatibility if item["blocking"] and not item["compatible"]]
    optional_incompatibilities = [
        item["name"] for item in compatibility if not item["blocking"] and not item["compatible"]
    ]
    return {
        "plan": "platform_release_compatibility_matrix",
        "compatibility_matrix_schema_version": RELEASE_COMPATIBILITY_SCHEMA_VERSION,
        "release_candidate_status": manifest["release_candidate_status"],
        "compatible_for_release_candidate": not blocking_incompatibilities,
        "blocking_incompatibilities": blocking_incompatibilities,
        "optional_incompatibilities": optional_incompatibilities,
        "matrix": compatibility,
        "generated_from": {
            "manifest": manifest["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_summary_from_manifest(
    manifest: dict[str, Any],
    compatibility: dict[str, Any],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact release summary from RC contract pieces."""

    return {
        "plan": "platform_release_summary",
        "release_summary_schema_version": RELEASE_SUMMARY_SCHEMA_VERSION,
        "platform": manifest["platform"],
        "release_candidate_status": manifest["release_candidate_status"],
        "release_stage": manifest["release_stage"],
        "current_version": manifest["current_version"],
        "migration_revision": manifest["migration_revision"],
        "repository_head": manifest["repository_head"],
        "compatible_for_release_candidate": compatibility["compatible_for_release_candidate"],
        "blocking_gate_count": len(manifest["blocking_gates"]),
        "optional_degradation_count": len(manifest["optional_degradations"]),
        "artifact_count": artifacts["artifact_count"],
        "required_artifact_count": artifacts["required_artifact_count"],
        "validation_command_count": len(manifest["validation_commands"]),
        "safe_to_run_without_ai": manifest["evidence_summary"]["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "generated_from": {
            "manifest": manifest["plan"],
            "compatibility": compatibility["plan"],
            "artifacts": artifacts["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_contract_from_manifest(
    manifest: dict[str, Any],
    ci_contract: dict[str, Any],
) -> dict[str, Any]:
    """Build the reusable release contract from the RC manifest."""

    metadata = build_release_metadata_from_manifest(manifest)
    artifacts = build_release_artifact_catalog_from_manifest(manifest)
    compatibility = build_release_compatibility_matrix_from_manifest(manifest)
    summary = build_release_summary_from_manifest(manifest, compatibility, artifacts)
    return {
        "plan": "platform_release_contract",
        "release_contract_schema_version": RELEASE_CONTRACT_SCHEMA_VERSION,
        "release_candidate_status": manifest["release_candidate_status"],
        "release_stage": manifest["release_stage"],
        "current_version": manifest["current_version"],
        "metadata": metadata,
        "manifest": manifest,
        "summary": summary,
        "compatibility": compatibility,
        "artifacts": artifacts,
        "ci_contract": ci_contract,
        "blocking_gates": manifest["blocking_gates"],
        "optional_degradations": manifest["optional_degradations"],
        "validation_commands": manifest["validation_commands"],
        "generated_from": {
            "manifest": manifest["plan"],
            "ci_contract": ci_contract["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_release_contract(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    readiness = build_release_candidate_readiness(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    ci_contract = build_release_candidate_ci_contract_from_readiness(readiness)
    manifest = build_release_candidate_manifest_from_readiness(readiness, ci_contract)
    return build_release_contract_from_manifest(manifest, ci_contract)


def build_release_artifact_catalog(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    manifest = build_release_candidate_manifest(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_release_artifact_catalog_from_manifest(manifest)


def build_release_compatibility_matrix(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    manifest = build_release_candidate_manifest(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    return build_release_compatibility_matrix_from_manifest(manifest)


def build_release_summary(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    manifest = build_release_candidate_manifest(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    artifacts = build_release_artifact_catalog_from_manifest(manifest)
    compatibility = build_release_compatibility_matrix_from_manifest(manifest)
    return build_release_summary_from_manifest(manifest, compatibility, artifacts)


def build_release_candidate_readiness(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Build the complete non-executing RC readiness payload."""

    evidence = build_release_candidate_evidence(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
        evidence_limit=evidence_limit,
    )
    command_catalog = build_release_candidate_command_catalog()
    gates = build_release_candidate_gates_from_evidence(evidence)
    checklist = build_release_candidate_checklist_from_gates(gates, command_catalog)
    return {
        "plan": "platform_release_candidate_readiness",
        "release_candidate_schema_version": RELEASE_CANDIDATE_SCHEMA_VERSION,
        "platform": evidence["platform"],
        "release_candidate_status": _release_candidate_status(gates),
        "safe_to_run_without_ai": evidence["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "core_blocking": True,
        "document_management_blocking": True,
        "blocking_failures": gates["blocking_failures"],
        "degraded_gates": gates["degraded_gates"],
        "degraded_capabilities": evidence["degraded_capabilities"],
        "evidence_consistency_status": evidence["evidence_consistency_status"],
        "command_catalog": command_catalog,
        "evidence": evidence,
        "gates": gates,
        "checklist": checklist,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }
