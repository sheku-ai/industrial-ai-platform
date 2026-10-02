#!/usr/bin/env python3
from __future__ import annotations

import atexit
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from readiness_contract_smoke import public_readiness_contract_valid  # noqa: E402

from app.services.product_acceptance.gateway import AcceptanceHttpClient  # noqa: E402

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR_REFERENCE = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))
AUTH_EMAIL = os.getenv("ACCEPTANCE_AUTH_EMAIL")
AUTH_PASSWORD = os.getenv("ACCEPTANCE_AUTH_PASSWORD")

HTTP_CLIENT: AcceptanceHttpClient | None = None

REQUIRED_RECOVERY_RESOURCES = (
    "platform_postgresql",
    "identity_postgresql",
    "object_storage",
    "application_configuration",
)

REQUIRED_VERIFICATION_CHECKS = (
    "database_connectivity_verified",
    "schema_version_verified",
    "record_counts_verified",
    "object_storage_access_verified",
    "artifact_checksums_verified",
    "organization_isolation_verified",
    "knowledge_lineage_verified",
    "enterprise_search_verified",
    "conversation_persistence_verified",
    "document_registration_verified",
    "assistant_runtime_verified",
    "audit_runtime_verified",
)


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    if HTTP_CLIENT is None:
        return False, {"error": "recovery_smoke_http_client_not_initialized"}
    result = HTTP_CLIENT.request(method, path, payload=payload)
    if result.ok:
        return True, result.data
    return False, {"status": result.status_code, "error": result.data or result.error}


def _finish(
    *,
    passed: bool,
    policy_id: str | None = None,
    backup_id: str | None = None,
    restore_id: str | None = None,
    verification_id: str | None = None,
    readiness: Any | None = None,
    production_acceptance: Any | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> int:
    recovery_acceptance = (
        production_acceptance.get("recovery_acceptance", {}) if isinstance(production_acceptance, dict) else {}
    )
    physical_execution = (
        (readiness.get("evidence_freshness") or {}).get("physical_provider_execution", {})
        if isinstance(readiness, dict)
        else {}
    )
    output = {
        "passed": passed,
        "policy_id": policy_id,
        "backup_id": backup_id,
        "restore_id": restore_id,
        "verification_id": verification_id,
        "recovery_readiness": readiness.get("status") if isinstance(readiness, dict) else None,
        "recovery_acceptance": recovery_acceptance.get("status"),
        "physical_provider_execution_evidenced": physical_execution.get("ready") is True,
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth")
        if isinstance(readiness, dict)
        else None,
        "llm_used": readiness.get("llm_used") if isinstance(readiness, dict) else None,
        "qdrant_used": readiness.get("qdrant_used") if isinstance(readiness, dict) else None,
        "errors": errors or [],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


def _require_step(ok: bool, payload: Any, step: str, errors: list[dict[str, Any]]) -> bool:
    if ok:
        return True
    errors.append({"step": step, "details": payload})
    return False


def _provider_execution_payload(
    *,
    operation: str,
    resource_type: str,
    execution: dict[str, Any],
    suffix: str,
) -> dict[str, Any]:
    observed_at = datetime.now(UTC).isoformat()
    return {
        "scope": "platform",
        "organization_id": None,
        "operation": operation,
        "resource_type": resource_type,
        "execution_entity_id": execution["id"],
        "provider_type": execution["provider_type"],
        "provider_execution_id": f"smoke-{operation}-{resource_type}-{suffix}",
        "execution_status": "succeeded",
        "started_at": observed_at,
        "completed_at": observed_at,
        "observed_at": observed_at,
        "evidence_source": "smoke_external_evidence",
        "correlation_id": execution["correlation_id"],
        "idempotency_key": f"smoke-{operation}-{resource_type}-{suffix}",
        "reference_payload": {"source": "external_evidence"},
    }


def main() -> int:
    global HTTP_CLIENT

    suffix = str(int(time.time()))
    root = Path(__file__).resolve().parents[3]
    release_manifest = json.loads((root / "release/manifest.json").read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = []

    HTTP_CLIENT = AcceptanceHttpClient(API_BASE_URL, f"recovery-smoke-{suffix}", timeout=TIMEOUT_SECONDS)
    authentication = HTTP_CLIENT.authenticate(AUTH_EMAIL, AUTH_PASSWORD)
    if not authentication.ok:
        errors.append(
            {
                "step": "authentication",
                "details": {
                    "status": authentication.status_code,
                    "error": authentication.data or authentication.error,
                },
            }
        )
        return _finish(passed=False, errors=errors)
    atexit.register(HTTP_CLIENT.logout_best_effort)

    ok, policy = _call(
        "POST",
        "/platform/recovery/policies",
        {
            "scope": "platform",
            "name": f"Smoke Recovery Policy {suffix}",
            "provider_type": "external_evidence",
            "provider_reference": "smoke-external-evidence-registry",
            "database_backup_enabled": True,
            "object_storage_backup_enabled": True,
            "configuration_backup_enabled": True,
            "rpo_minutes": 60,
            "rto_minutes": 240,
            "evidence_max_age_hours": 168,
            "verification_required": True,
            "created_by": ACTOR_REFERENCE,
        },
    )
    if not _require_step(ok, policy, "create_policy", errors):
        return _finish(passed=False, errors=errors)
    policy_id = policy.get("id") if isinstance(policy, dict) else None
    if not policy_id:
        errors.append({"step": "create_policy", "details": "missing_policy_id"})
        return _finish(passed=False, errors=errors)

    ok, activated = _call("POST", f"/platform/recovery/policies/{policy_id}/activate", {})
    if not _require_step(ok, activated, "activate_policy", errors):
        return _finish(passed=False, policy_id=policy_id, errors=errors)
    if activated.get("id") != policy_id or activated.get("status") != "active":
        errors.append({"step": "activate_policy", "details": "activated_policy_mismatch"})
        return _finish(passed=False, policy_id=policy_id, errors=errors)

    ok, backup = _call(
        "POST",
        "/platform/recovery/backups",
        {
            "scope": "platform",
            "policy_id": policy_id,
            "provider_type": "external_evidence",
            "idempotency_key": f"smoke-backup-{suffix}",
            "backup_type": "external",
            "database_included": True,
            "object_storage_included": True,
            "configuration_included": True,
            "consistent_snapshot": True,
            "manifest_hash": f"manifest-{suffix}",
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not _require_step(ok, backup, "register_backup", errors):
        return _finish(passed=False, policy_id=policy_id, errors=errors)
    backup_id = backup.get("id") if isinstance(backup, dict) else None
    if not backup_id or backup.get("policy_id") != policy_id:
        errors.append({"step": "register_backup", "details": "backup_policy_mismatch"})
        return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, errors=errors)

    for resource_type in REQUIRED_RECOVERY_RESOURCES:
        ok, provider_evidence = _call(
            "POST",
            "/platform/recovery/provider-execution-evidence",
            _provider_execution_payload(
                operation="backup",
                resource_type=resource_type,
                execution=backup,
                suffix=suffix,
            ),
        )
        if not _require_step(ok, provider_evidence, f"backup_provider_evidence_{resource_type}", errors):
            return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, errors=errors)

    artifact_metadata = {
        "platform_postgresql": {
            "source": "external_evidence",
            "postgresql_authority": "platform",
            "postgresql_version": release_manifest["supported_postgresql_version"],
            "alembic_revision": release_manifest["alembic_head"],
        },
        "identity_postgresql": {
            "source": "external_evidence",
            "postgresql_authority": "identity",
            "postgresql_version": release_manifest["supported_postgresql_version"],
        },
        "object_storage": {"source": "external_evidence"},
        "application_configuration": {"source": "external_evidence"},
        "migration_manifest": {
            "source": "external_evidence",
            "alembic_revision": release_manifest["alembic_head"],
        },
        "release_manifest": {
            "source": "external_evidence",
            "application_version": release_manifest["version"],
        },
    }
    for resource_type, metadata_payload in artifact_metadata.items():
        ok, artifact = _call(
            "POST",
            f"/platform/recovery/backups/{backup_id}/artifacts",
            {
                "artifact_type": f"{resource_type}_artifact",
                "resource_type": resource_type,
                "storage_location_masked": "external_evidence_registered",
                "checksum_algorithm": "sha256",
                "checksum": f"{resource_type}-{suffix}",
                "verification_status": "verified",
                "metadata_payload": metadata_payload,
            },
        )
        if not _require_step(ok, artifact, f"artifact_{resource_type}", errors):
            return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, errors=errors)

    ok, completed_backup = _call(
        "POST",
        f"/platform/recovery/backups/{backup_id}/complete",
        {"manifest_hash": f"manifest-{suffix}", "consistent_snapshot": True},
    )
    if not _require_step(ok, completed_backup, "complete_backup", errors):
        return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, errors=errors)

    ok, restore = _call(
        "POST",
        "/platform/recovery/restores",
        {
            "scope": "platform",
            "policy_id": policy_id,
            "backup_execution_id": backup_id,
            "provider_type": "external_evidence",
            "idempotency_key": f"smoke-restore-{suffix}",
            "restore_target_type": "isolated_validation_environment",
            "destructive_operation": False,
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not _require_step(ok, restore, "register_restore", errors):
        return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, errors=errors)
    restore_id = restore.get("id") if isinstance(restore, dict) else None
    if not restore_id or restore.get("policy_id") != policy_id or restore.get("backup_execution_id") != backup_id:
        errors.append({"step": "register_restore", "details": "restore_lineage_mismatch"})
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            errors=errors,
        )

    for resource_type in REQUIRED_RECOVERY_RESOURCES:
        ok, provider_evidence = _call(
            "POST",
            "/platform/recovery/provider-execution-evidence",
            _provider_execution_payload(
                operation="restore",
                resource_type=resource_type,
                execution=restore,
                suffix=suffix,
            ),
        )
        if not _require_step(ok, provider_evidence, f"restore_provider_evidence_{resource_type}", errors):
            return _finish(
                passed=False,
                policy_id=policy_id,
                backup_id=backup_id,
                restore_id=restore_id,
                errors=errors,
            )

    ok, completed_restore = _call(
        "POST",
        f"/platform/recovery/restores/{restore_id}/complete",
        {"database_restored": True, "object_storage_restored": True, "configuration_restored": True},
    )
    if not _require_step(ok, completed_restore, "complete_restore", errors):
        return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, restore_id=restore_id, errors=errors)

    ok, verification = _call(
        "POST",
        f"/platform/recovery/restores/{restore_id}/verifications",
        {"verification_type": "external_evidence", "verified_by": ACTOR_REFERENCE},
    )
    if not _require_step(ok, verification, "create_verification", errors):
        return _finish(passed=False, policy_id=policy_id, backup_id=backup_id, restore_id=restore_id, errors=errors)
    verification_id = verification.get("id") if isinstance(verification, dict) else None
    if not verification_id or verification.get("restore_execution_id") != restore_id:
        errors.append({"step": "create_verification", "details": "verification_restore_mismatch"})
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            verification_id=verification_id,
            errors=errors,
        )

    restore_correlation_id = restore.get("correlation_id")
    for check_code in REQUIRED_VERIFICATION_CHECKS:
        ok, check_evidence = _call(
            "POST",
            f"/platform/recovery/verifications/{verification_id}/check-evidence",
            {
                "check_code": check_code,
                "check_status": "passed",
                "observed_at": datetime.now(UTC).isoformat(),
                "evidence_source": "smoke_external_evidence",
                "correlation_id": restore_correlation_id,
                "idempotency_key": f"smoke-verification-{check_code}-{suffix}",
                "reference_payload": {"source": "external_evidence"},
            },
        )
        if not _require_step(ok, check_evidence, f"verification_evidence_{check_code}", errors):
            return _finish(
                passed=False,
                policy_id=policy_id,
                backup_id=backup_id,
                restore_id=restore_id,
                verification_id=verification_id,
                errors=errors,
            )

    ok, completed_verification = _call(
        "POST",
        f"/platform/recovery/verifications/{verification_id}/complete",
        {
            "database_connectivity_verified": True,
            "schema_version_verified": True,
            "record_counts_verified": True,
            "object_storage_access_verified": True,
            "artifact_checksums_verified": True,
            "organization_isolation_verified": True,
            "knowledge_lineage_verified": True,
            "enterprise_search_verified": True,
            "conversation_persistence_verified": True,
            "document_registration_verified": True,
            "assistant_runtime_verified": True,
            "audit_runtime_verified": True,
            "verified_by": ACTOR_REFERENCE,
            "verification_payload": {"source": "external_evidence"},
        },
    )
    if not _require_step(ok, completed_verification, "complete_verification", errors):
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            verification_id=verification_id,
            errors=errors,
        )

    ok, readiness = _call("GET", "/platform/recovery/readiness?scope=platform")
    if not _require_step(ok, readiness, "readiness", errors):
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            verification_id=verification_id,
            errors=errors,
        )

    active_policy = readiness.get("active_policy", {}) if isinstance(readiness, dict) else {}
    latest_backup = readiness.get("latest_backup", {}) if isinstance(readiness, dict) else {}
    latest_restore = readiness.get("latest_restore", {}) if isinstance(readiness, dict) else {}
    latest_verification = readiness.get("latest_restore_verification", {}) if isinstance(readiness, dict) else {}
    if (
        active_policy.get("id") != policy_id
        or latest_backup.get("id") != backup_id
        or latest_backup.get("policy_id") != policy_id
        or latest_restore.get("id") != restore_id
        or latest_restore.get("backup_execution_id") != backup_id
        or latest_verification.get("id") != verification_id
        or latest_verification.get("restore_execution_id") != restore_id
    ):
        errors.append({"step": "readiness", "details": "stale_or_unrelated_recovery_evidence"})
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            verification_id=verification_id,
            readiness=readiness,
            errors=errors,
        )

    ok, production_acceptance = _call(
        "POST",
        "/platform/production-acceptance/runs",
        {
            "scope": "platform",
            "idempotency_key": f"smoke-production-acceptance-recovery-{suffix}",
            "requested_by": ACTOR_REFERENCE,
        },
    )
    if not _require_step(ok, production_acceptance, "production_acceptance", errors):
        return _finish(
            passed=False,
            policy_id=policy_id,
            backup_id=backup_id,
            restore_id=restore_id,
            verification_id=verification_id,
            readiness=readiness,
            errors=errors,
        )

    recovery_gate_statuses = (
        {item.get("gate_code"): item.get("status") for item in readiness.get("gates", [])}
        if isinstance(readiness, dict)
        else {}
    )
    recovery_acceptance = (
        production_acceptance.get("recovery_acceptance", {}) if isinstance(production_acceptance, dict) else {}
    )
    physical_execution = (
        (readiness.get("evidence_freshness") or {}).get("physical_provider_execution", {})
        if isinstance(readiness, dict)
        else {}
    )
    passed = (
        not errors
        and readiness.get("status") == "passed"
        and public_readiness_contract_valid(readiness.get("evidence_contract"), domain="recovery")
        and bool(recovery_gate_statuses)
        and all(status == "passed" for status in recovery_gate_statuses.values())
        and physical_execution.get("required_by_recovery_control_plane") is True
        and physical_execution.get("ready") is True
        and recovery_acceptance.get("status") == readiness.get("status")
    )
    return _finish(
        passed=passed,
        policy_id=policy_id,
        backup_id=backup_id,
        restore_id=restore_id,
        verification_id=verification_id,
        readiness=readiness,
        production_acceptance=production_acceptance,
        errors=errors,
    )


if __name__ == "__main__":
    sys.exit(main())
