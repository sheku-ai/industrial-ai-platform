#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
RUN_KEY = os.getenv("SMOKE_RELEASE_GOVERNANCE_KEY", "release-governance")
SOURCE_REVISION = os.getenv("SMOKE_SOURCE_REVISION", "controlled-release-evidence")
SCHEMA_REVISION = os.getenv("SMOKE_SCHEMA_REVISION", "20260714_940")
FROM_SCHEMA_REVISION = os.getenv("SMOKE_FROM_SCHEMA_REVISION", "20260714_930")
BUILD_TIMESTAMP = os.getenv("SMOKE_BUILD_TIMESTAMP", "2026-07-14T00:00:00+00:00")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "45"))
BASELINE_IDENTITY = f"community:1.3.1:stable:baseline-{SOURCE_REVISION}"
RELEASE_CANDIDATE_IDENTITY = f"community:1.3.2-rc.1:release_candidate:{SOURCE_REVISION}"
CONTRACT_VERSION = "release_artifact_governance.v1"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Authorization-Scope": "platform",
            "X-Principal-Type": "reference_principal",
            "X-Actor-Reference": ACTOR,
            "X-Correlation-ID": f"release-governance-smoke-{RUN_KEY}",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    try:
        return True, _request(method, path, payload)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        return False, {"status": exc.code, "detail": detail}
    except Exception as exc:  # pragma: no cover - smoke diagnostics
        return False, {"error": str(exc)}


def _has_governed_postgresql_evidence(gate: dict[str, Any]) -> bool:
    return (
        gate.get("status") == "passed"
        and gate.get("evidence_origin") == "release_governance_runtime"
        and bool(gate.get("evidence_reference"))
    )


def _logical_release_matches(release: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(release.get(field) == value for field, value in expected.items())


def _list_logical_releases(identity: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    listed, payload = _call("GET", f"/platform/releases?edition={identity['edition']}")
    if not listed or not isinstance(payload, list):
        return False, []
    matches = [item for item in payload if _logical_release_matches(item, identity)]
    return True, sorted(matches, key=lambda item: (item.get("created_at", ""), item.get("id", "")), reverse=True)


def _resolve_logical_release(
    *,
    identity: dict[str, Any],
    create_payload: dict[str, Any],
) -> tuple[bool, dict[str, Any], bool, int]:
    listed, existing = _list_logical_releases(identity)
    if not listed:
        return False, {"error": "governed_release_inventory_unavailable"}, False, 0
    if existing:
        return True, existing[0], True, len(existing)
    created, release = _call("POST", "/platform/releases", create_payload)
    if not created:
        return False, release, False, 0
    relisted, persisted = _list_logical_releases(identity)
    if not relisted or len(persisted) != 1 or persisted[0].get("id") != release.get("id"):
        return False, {"error": "governed_release_read_after_write_failed"}, False, 0
    return True, persisted[0], False, 0


def _release_count_unchanged(identity: dict[str, Any], before_count: int, reused: bool) -> bool:
    listed, persisted = _list_logical_releases(identity)
    if not listed:
        return False
    expected = before_count if reused else before_count + 1
    return len(persisted) == expected


def main() -> int:
    errors: list[dict[str, Any]] = []

    provisioned, provision = _call("POST", "/reference-tenant/provision", {"requested_by": ACTOR})
    if not provisioned:
        errors.append({"step": "provision_reference_tenant", "details": provision})

    baseline_identity = {
        "version": "1.3.1",
        "edition": "community",
        "channel": "stable",
        "contract_version": CONTRACT_VERSION,
        "source_repository": "sheku-ai/industrial-ai-platform",
        "source_revision": f"baseline-{SOURCE_REVISION}",
    }
    baseline_ok, baseline, baseline_reused, baseline_count_before = _resolve_logical_release(
        identity=baseline_identity,
        create_payload={
            "release_code": "governed-baseline-community-1.3.1",
            "version": "1.3.1",
            "edition": "community",
            "channel": "stable",
            "source_repository": "sheku-ai/industrial-ai-platform",
            "source_revision": f"baseline-{SOURCE_REVISION}",
            "idempotency_key": f"governed-release:{BASELINE_IDENTITY}",
            "created_by": ACTOR,
        },
    )
    if not baseline_ok:
        errors.append({"step": "create_baseline_release", "details": baseline})

    release_identity = {
        "version": "1.3.2-rc.1",
        "edition": "community",
        "channel": "release_candidate",
        "contract_version": CONTRACT_VERSION,
        "source_repository": "sheku-ai/industrial-ai-platform",
        "source_revision": SOURCE_REVISION,
    }
    release_ok, release, release_reused, release_count_before = _resolve_logical_release(
        identity=release_identity,
        create_payload={
            "release_code": "governed-rc-community-1.3.2-rc.1",
            "version": "1.3.2-rc.1",
            "edition": "community",
            "channel": "release_candidate",
            "source_repository": "sheku-ai/industrial-ai-platform",
            "source_revision": SOURCE_REVISION,
            "source_branch": "main",
            "idempotency_key": f"governed-release:{RELEASE_CANDIDATE_IDENTITY}",
            "created_by": ACTOR,
        },
    )
    if not release_ok:
        errors.append({"step": "create_release", "details": release})
    release_id = release.get("id")

    build_timestamp = BUILD_TIMESTAMP
    build_ok, build = (
        _call(
            "POST",
            f"/platform/releases/{release_id}/builds",
            {
                "build_number": "controlled-community-1.3.2-rc.1",
                "build_timestamp": build_timestamp,
                "builder_type": "manual_evidence",
                "builder_reference": "release-governance-smoke",
                "source_revision": SOURCE_REVISION,
                "target_platform": "container",
                "target_architecture": "multi_arch",
                "build_profile": "production",
                "reproducibility_evidence": {},
                "idempotency_key": f"release-build:{RELEASE_CANDIDATE_IDENTITY}",
            },
        )
        if release_id
        else (False, {})
    )
    if not build_ok:
        errors.append({"step": "create_build", "details": build})
    build_id = build.get("id")

    manifest_payload = {
        "manifest_version": "1",
        "application_version": release.get("version"),
        "source_revision": SOURCE_REVISION,
        "build_timestamp": build_timestamp,
        "python_version": "3.12",
        "node_version": "20",
        "database_schema_revision": SCHEMA_REVISION,
        "container_runtime": "OCI-compatible",
        "target_platforms": ["container"],
        "target_architectures": ["amd64", "arm64"],
        "dependency_summary": {"evidence_source": "controlled_smoke_evidence"},
        "component_versions": {
            "api": release.get("version"),
            "portal": release.get("version"),
            "workers": release.get("version"),
            "scheduler": release.get("version"),
            "migrator": SCHEMA_REVISION,
            "object_storage_integration": "s3-compatible",
            "database_compatibility": "postgresql-16",
        },
        "configuration_profile": "production",
        "manifest_payload": {"evidence_source": "controlled_smoke_evidence"},
    }
    manifest_ok, manifest = (
        _call("POST", f"/platform/builds/{build_id}/manifest", manifest_payload) if build_id else (False, {})
    )
    if not manifest_ok:
        errors.append({"step": "register_build_manifest", "details": manifest})

    complete_ok, completed_build = (
        _call(
            "POST",
            f"/platform/builds/{build_id}/complete",
            {
                "reproducibility_evidence": {
                    "evidence_source": "controlled_smoke_evidence",
                    "independent_attempts": 1,
                    "repeated_build_digest_match": False,
                },
                "result_evidence": {
                    "build_execution": "not_performed_by_smoke",
                    "manifest_hash": manifest.get("manifest_hash"),
                },
            },
        )
        if build_id
        else (False, {})
    )
    if not complete_ok:
        errors.append({"step": "complete_build", "details": completed_build})

    artifact_codes = ("api-image", "portal-image", "migration-bundle")
    deployment_ok, deployment = (
        _call(
            "POST",
            f"/platform/releases/{release_id}/deployment-manifest",
            {
                "build_id": build_id,
                "manifest_version": "1",
                "deployment_profile": "on_premise",
                "deployment_strategy": "external",
                "required_services": ["postgresql", "migrator", "api", "portal", "workers", "scheduler"],
                "optional_services": ["ai_provider", "vector_database"],
                "health_checks": [{"service": "api", "contract": "/health"}],
                "readiness_checks": [{"service": "api", "contract": "/health/ready"}],
                "startup_order": ["postgresql", "migrator", "api", "workers", "scheduler", "portal"],
                "configuration_requirements": {"profile": "production", "evidence_source": "controlled_smoke_evidence"},
                "secret_requirements": ["database_credentials", "object_storage_credentials"],
                "storage_requirements": {"database": "persistent", "object_storage": "persistent"},
                "network_requirements": {"encrypted_external_transport": True},
                "resource_requirements": {"governed_limits_required": True},
                "migration_requirements": {"target_revision": SCHEMA_REVISION},
                "rollback_target_release_id": baseline.get("id"),
                "rollback_procedure_reference": "controlled-external-procedure",
                "manifest_payload": {
                    "required_artifact_codes": list(artifact_codes),
                    "required_compatibility_types": ["database_schema", "previous_release"],
                    "evidence_source": "controlled_smoke_evidence",
                },
            },
        )
        if release_id and build_id and baseline.get("id")
        else (False, {})
    )
    if not deployment_ok:
        errors.append({"step": "register_deployment_manifest", "details": deployment})

    artifacts: list[dict[str, Any]] = []
    artifact_specs = (
        ("api-image", "container_image", "api"),
        ("portal-image", "container_image", "portal"),
        ("migration-bundle", "migration_bundle", "migrator"),
    )
    for code, artifact_type, component in artifact_specs:
        controlled_evidence = {
            "code": code,
            "release_id": release_id,
            "build_id": build_id,
            "source_revision": SOURCE_REVISION,
        }
        controlled_digest = _digest(controlled_evidence)
        created, artifact = _call(
            "POST",
            f"/platform/releases/{release_id}/artifacts",
            {
                "build_id": build_id,
                "artifact_code": code,
                "artifact_type": artifact_type,
                "component": component,
                "edition": "community",
                "platform": "container",
                "architecture": "multi_arch",
                "media_type": "application/vnd.oci.image.manifest.v1+json"
                if artifact_type == "container_image"
                else "application/octet-stream",
                "artifact_reference": f"controlled-evidence:{code}:{RELEASE_CANDIDATE_IDENTITY}",
                "size_bytes": len(json.dumps(controlled_evidence).encode()),
                "checksum_algorithm": "sha256",
                "checksum": controlled_digest,
                "digest_algorithm": "sha256",
                "digest": f"sha256:{controlled_digest}",
                "signature_status": "not_provided",
                "provenance_status": "pending",
                "sbom_status": "pending",
                "required": True,
                "metadata_payload": {"evidence_source": "controlled_smoke_evidence", "binary_not_created": True},
            },
        )
        if not created:
            errors.append({"step": f"register_artifact:{code}", "details": artifact})
            continue
        verified, artifact = _call(
            "POST",
            f"/platform/artifacts/{artifact.get('id')}/verify",
            {
                "checksum_verified": True,
                "digest_verified": True,
                "provenance_status": "verified",
                "sbom_status": "available",
                "signature_status": "not_provided",
                "evidence_payload": {
                    "evidence_source": "controlled_smoke_evidence",
                    "binary_not_created": True,
                    "external_validation_only": True,
                },
            },
        )
        if not verified:
            errors.append({"step": f"verify_artifact:{code}", "details": artifact})
        artifacts.append(artifact)

    compatibility_records: list[dict[str, Any]] = []
    for compatibility_type, minimum, maximum in (
        ("database_schema", SCHEMA_REVISION, SCHEMA_REVISION),
        ("previous_release", baseline.get("version"), baseline.get("version")),
    ):
        created, compatibility = _call(
            "POST",
            f"/platform/releases/{release_id}/compatibility",
            {
                "compatibility_type": compatibility_type,
                "minimum_version": minimum,
                "maximum_version": maximum,
                "compatible": True,
                "requirements": {},
                "evidence_payload": {"evidence_source": "controlled_smoke_evidence"},
            },
        )
        if not created:
            errors.append({"step": f"compatibility:{compatibility_type}", "details": compatibility})
        compatibility_records.append(compatibility)

    migration_ok, migration = _call(
        "POST",
        f"/platform/releases/{release_id}/migration-requirements",
        {
            "from_revision": FROM_SCHEMA_REVISION,
            "to_revision": SCHEMA_REVISION,
            "migration_required": True,
            "migration_strategy": "forward_only",
            "reversible": False,
            "irreversible_reason": "Published forward-only release governance migration.",
            "preconditions": [{"current_revision": "20260713_910"}],
            "postconditions": [{"target_revision": SCHEMA_REVISION}],
            "evidence_payload": {
                "evidence_source": "controlled_smoke_evidence",
                "migration_execution": "not_performed_by_smoke",
                "repository_target_revision": SCHEMA_REVISION,
                "database_current_revision": SCHEMA_REVISION,
                "single_alembic_head": True,
                "pending_migrations_count": 0,
                "schema_compatibility_status": "compatible",
                "release_id": release_id,
                "build_id": build_id,
                "build_manifest_id": manifest.get("id"),
                "from_revision": FROM_SCHEMA_REVISION,
                "to_revision": SCHEMA_REVISION,
            },
        },
    )
    if not migration_ok:
        errors.append({"step": "register_migration_requirement", "details": migration})

    rollback_ok, rollback = _call(
        "POST",
        f"/platform/releases/{release_id}/rollback-target",
        {
            "rollback_target_release_id": baseline.get("id"),
            "rollback_supported": True,
            "rollback_strategy": "external",
            "database_rollback_supported": False,
            "application_rollback_supported": True,
            "required_actions": [{"action": "restore_previous_application_artifacts"}],
            "blockers": [],
            "evidence_payload": {"evidence_source": "controlled_smoke_evidence", "rollback_execution": "not_performed"},
            "verified_at": BUILD_TIMESTAMP,
        },
    )
    if not rollback_ok:
        errors.append({"step": "register_rollback_target", "details": rollback})

    evaluated, acceptance = _call("POST", f"/platform/releases/{release_id}/evaluate", {})
    if not evaluated or acceptance.get("status") != "passed":
        errors.append({"step": "evaluate_release", "details": acceptance})
    readiness_ok, readiness = _call("GET", f"/platform/releases/{release_id}/readiness")
    if (
        not readiness_ok
        or readiness.get("acceptance_status") != "passed"
        or not public_readiness_contract_valid(
            readiness.get("evidence_contract"), domain="release_governance"
        )
    ):
        errors.append({"step": "read_release_readiness", "details": readiness})

    production_ok, production = _call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"release-governance-production:{RELEASE_CANDIDATE_IDENTITY}",
            "requested_by": ACTOR,
        },
    )
    deployment_gates = {
        item.get("gate_code"): item for item in production.get("gate_results", []) if item.get("domain") == "deployment"
    }
    expected_gates = {
        "build_manifest_valid",
        "deployment_manifest_valid",
        "required_artifacts_present",
        "required_artifacts_verified",
        "checksums_valid",
        "digests_valid",
        "provenance_available",
        "sbom_available",
        "compatibility_valid",
        "migration_requirements_valid",
        "rollback_target_valid",
        "edition_boundary_valid",
    }
    governed_evidence = all(
        _has_governed_postgresql_evidence(deployment_gates.get(code, {}))
        for code in expected_gates
    )
    if not production_ok or not governed_evidence:
        errors.append({"step": "production_acceptance_deployment_evidence", "details": deployment_gates})

    if not _release_count_unchanged(baseline_identity, baseline_count_before, baseline_reused):
        errors.append({"step": "baseline_release_identity_count_changed"})
    if not _release_count_unchanged(release_identity, release_count_before, release_reused):
        errors.append({"step": "release_candidate_identity_count_changed"})

    output = {
        "passed": not errors,
        "baseline_release_id": baseline.get("id"),
        "release_id": release_id,
        "release_reused": release_reused,
        "baseline_release_reused": baseline_reused,
        "build_id": build_id,
        "build_manifest_id": manifest.get("id"),
        "deployment_manifest_id": deployment.get("id"),
        "artifact_ids": [item.get("id") for item in artifacts],
        "compatibility_ids": [item.get("id") for item in compatibility_records],
        "migration_requirement_id": migration.get("id"),
        "rollback_target_id": rollback.get("id"),
        "rollback_target_release_id": baseline.get("id"),
        "acceptance_evidence_id": acceptance.get("id"),
        "release_acceptance_status": acceptance.get("status"),
        "deployment_gates_governed": governed_evidence,
        "production_acceptance_run_id": production.get("run_id"),
        "llm_used": False,
        "qdrant_used": False,
        "external_build_performed": False,
        "deployment_performed": False,
        "rollback_performed": False,
        "errors": errors,
    }
    sys.stdout.write(json.dumps(output, indent=2, sort_keys=True, default=str) + "\n")
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
