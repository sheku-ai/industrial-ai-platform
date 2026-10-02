from __future__ import annotations

from dataclasses import dataclass

CONTRACT_VERSION = "production_acceptance.v5"


@dataclass(frozen=True)
class ProductionGateDefinition:
    gate_code: str
    domain: str
    mandatory: bool
    description: str
    evidence_requirements: tuple[str, ...]
    evaluation_strategy: str
    blocker_code: str
    warning_code: str
    contract_version: str = CONTRACT_VERSION


def _gate(gate_code: str, domain: str, description: str) -> ProductionGateDefinition:
    return ProductionGateDefinition(
        gate_code=gate_code,
        domain=domain,
        mandatory=True,
        description=description,
        evidence_requirements=(f"{domain}_evidence_contract",),
        evaluation_strategy="authoritative_evidence_contract",
        blocker_code=f"{gate_code.upper()}_NOT_PASSED",
        warning_code=f"{gate_code}_warning",
    )


_GATES: dict[str, tuple[tuple[str, str], ...]] = {
    "functional": (
        ("local_product_acceptance_passed", "Local Product Acceptance has a persisted successful execution."),
    ),
    "operational": (
        ("observability_evidence_available", "Persisted observability evidence is available."),
        ("observability_health_verified", "Persisted observability health is verified."),
        ("observability_signal_coverage", "Required persisted observability signals are covered."),
        ("observability_component_readiness", "Observed components and dependencies are ready."),
        ("observability_freshness_valid", "Persisted observability evidence remains fresh."),
    ),
    "security": (
        ("production_authentication_required", "Production authentication is enforced."),
        ("production_configuration_fail_closed", "Production configuration fails closed."),
        ("secret_placeholders_absent", "Unsafe placeholder secrets are absent."),
        ("cross_organization_access_blocked", "Cross-organization access is blocked."),
        ("audit_runtime_available", "Audit runtime evidence exists."),
        ("debug_disabled", "Debug mode is disabled for production."),
        ("cors_restricted", "CORS origins are explicit and restricted."),
        ("provider_execution_explicit", "Provider execution is explicit and AI remains optional."),
        ("security_findings_clear", "No blocking security findings remain open."),
    ),
    "recovery": (
        ("backup_policy_configured", "Backup policy is configured."),
        ("latest_backup_evidence_available", "Latest backup evidence is available."),
        ("latest_restore_verification_available", "Latest restore verification is available."),
        ("rpo_configured", "RPO is configured."),
        ("rto_configured", "RTO is configured."),
        ("object_storage_recovery_defined", "Object storage recovery is defined."),
        ("database_recovery_defined", "Database recovery is defined."),
        ("recovery_evidence_fresh", "Recovery evidence is fresh."),
    ),
    "deployment": (
        ("build_manifest_valid", "Build manifest is valid."),
        ("deployment_manifest_valid", "Deployment manifest is valid."),
        ("required_artifacts_present", "Required release artifacts are present."),
        ("required_artifacts_verified", "Required release artifacts are verified."),
        ("checksums_valid", "Artifact checksums are valid."),
        ("digests_valid", "Artifact digests are valid."),
        ("provenance_available", "Artifact provenance is available."),
        ("sbom_available", "SBOM evidence is available."),
        ("compatibility_valid", "Release compatibility is valid."),
        ("migration_requirements_valid", "Migration requirements are valid."),
        ("rollback_target_valid", "Rollback target is valid."),
        ("edition_boundary_valid", "Edition boundary is valid."),
    ),
    "capacity": (
        ("capacity_profile_defined", "A governed Capacity Profile is defined."),
        ("load_test_completed", "A governed Load Test completed with persisted results."),
        ("capacity_validated", "Observed capacity satisfies persisted target capacity."),
        ("capacity_bottlenecks_resolved", "No unresolved blocking Capacity findings remain."),
        ("production_capacity_ready", "Capacity acceptance is ready for production."),
    ),
    "portal": (
        ("principal_routes_available", "Principal portal routes are available."),
        ("portal_build_validated", "Portal build evidence is available."),
        ("portal_contract_validated", "Portal contract evidence is available."),
        ("negative_states_validated", "Negative portal states are validated."),
        ("permission_states_validated", "Permission states are validated."),
        ("cross_organization_states_validated", "Cross-organization states are validated."),
    ),
}

PRODUCTION_ACCEPTANCE_GATES = tuple(
    _gate(gate_code, domain, description)
    for domain, entries in _GATES.items()
    for gate_code, description in entries
)


def gates_by_domain() -> dict[str, tuple[ProductionGateDefinition, ...]]:
    return {
        domain: tuple(gate for gate in PRODUCTION_ACCEPTANCE_GATES if gate.domain == domain)
        for domain in _GATES
    }
