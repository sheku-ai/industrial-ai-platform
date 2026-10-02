#!/usr/bin/env python3
"""Fast contract checks for scripts/platform_lifecycle.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "platform_lifecycle.py"


def run_command(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except Exception as exc:  # pragma: no cover - diagnostic failure path
        raise AssertionError(
            f"expected JSON stdout rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc

    if completed.returncode != 0:
        raise AssertionError(f"command failed rc={completed.returncode} payload={payload}")
    return payload


def assert_status_contract(payload: dict) -> None:
    required = {
        "alembic_config",
        "alembic_cwd",
        "compatibility",
        "database_heads",
        "migration_required",
        "pending_revisions",
        "repository_heads",
        "startup_compatible",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise AssertionError(f"missing status keys: {missing}")

    if not isinstance(payload["database_heads"], list):
        raise AssertionError("database_heads must be a list")
    if not isinstance(payload["repository_heads"], list):
        raise AssertionError("repository_heads must be a list")
    if not isinstance(payload["migration_required"], bool):
        raise AssertionError("migration_required must be boolean")
    if not isinstance(payload["startup_compatible"], bool):
        raise AssertionError("startup_compatible must be boolean")


def assert_install_check_contract(payload: dict) -> None:
    if payload.get("plan") != "install_check":
        raise AssertionError("install-check must return plan=install_check")
    if not isinstance(payload.get("ready"), bool):
        raise AssertionError("install-check ready must be boolean")
    if not isinstance(payload.get("checks"), dict):
        raise AssertionError("install-check checks must be an object")
    if not isinstance(payload.get("profiles"), dict):
        raise AssertionError("install-check profiles must be an object")
    if not isinstance(payload.get("degraded_capabilities"), list):
        raise AssertionError("install-check degraded_capabilities must be a list")
    assert_status_contract(payload["status"])

    required_checks = {
        "alembic",
        "ai_services",
        "database",
        "document_management_evidence",
        "object_storage",
        "qdrant",
    }
    missing = sorted(required_checks - set(payload["checks"]))
    if missing:
        raise AssertionError(f"install-check missing checks: {missing}")

    required_profiles = {"core", "document_management", "ai_services"}
    missing_profiles = sorted(required_profiles - set(payload["profiles"]))
    if missing_profiles:
        raise AssertionError(f"install-check missing profiles: {missing_profiles}")
    for name in required_profiles:
        profile = payload["profiles"][name]
        if not isinstance(profile.get("ready"), bool):
            raise AssertionError(f"profile {name} ready must be boolean")
        if not isinstance(profile.get("blocking"), bool):
            raise AssertionError(f"profile {name} blocking must be boolean")
    if payload["profiles"]["core"].get("blocking") is not True:
        raise AssertionError("core profile must be blocking")
    if payload["profiles"]["document_management"].get("blocking") is not True:
        raise AssertionError("document_management profile must be blocking")
    if payload["profiles"]["ai_services"].get("blocking") is not False:
        raise AssertionError("ai_services profile must not block installation readiness")
    if payload["ready"] != payload["profiles"]["document_management"]["ready"]:
        raise AssertionError("install-check ready must follow document_management readiness")

    database = payload["checks"]["database"]
    if not isinstance(database.get("ready"), bool):
        raise AssertionError("database ready must be boolean")
    if not isinstance(database.get("configuration"), dict):
        raise AssertionError("database configuration must be an object")
    if database["configuration"].get("name") != "DATABASE_URL":
        raise AssertionError("database configuration must describe DATABASE_URL")
    if not isinstance(database.get("postgresql"), dict):
        raise AssertionError("database postgresql check must be an object")

    object_storage = payload["checks"]["object_storage"]
    if not isinstance(object_storage.get("ready"), bool):
        raise AssertionError("object_storage ready must be boolean")
    provider = object_storage.get("provider") or {}
    if provider.get("value") not in {"filesystem", "s3", "minio", "object_storage"}:
        raise AssertionError("object_storage provider must be supported")
    required_names = {item.get("name") for item in object_storage.get("required_configuration", [])}
    if provider.get("value") == "filesystem":
        expected = {"INDUSTRIAL_AI_STORAGE_FILESYSTEM_ROOT"}
    else:
        expected = {
            "OBJECT_STORAGE_ENDPOINT_URL",
            "OBJECT_STORAGE_ACCESS_KEY",
            "OBJECT_STORAGE_SECRET_KEY",
            "OBJECT_STORAGE_BUCKET",
        }
    if required_names != expected:
        raise AssertionError(f"object_storage required configuration mismatch: {sorted(required_names)}")

    vertical = payload["checks"]["document_management_evidence"]
    if not isinstance(vertical.get("ready"), bool):
        raise AssertionError("document_management evidence ready must be boolean")
    if vertical.get("postgresql_source_of_truth") is not True:
        raise AssertionError("document_management evidence must use PostgreSQL as source of truth")

    qdrant = payload["checks"]["qdrant"]
    if not isinstance(qdrant.get("ready"), bool):
        raise AssertionError("qdrant ready must be boolean")
    if qdrant.get("blocking") is not False:
        raise AssertionError("qdrant must not block installation readiness")
    qdrant_names = {item.get("name") for item in qdrant.get("configuration", [])}
    if qdrant_names != {"QDRANT_URL"}:
        raise AssertionError(f"qdrant configuration mismatch: {sorted(qdrant_names)}")
    if not qdrant["ready"]:
        degraded = set(payload["degraded_capabilities"])
        if not {"vector_search", "rag"}.issubset(degraded):
            raise AssertionError("missing qdrant must degrade vector_search and rag")

    ai_services = payload["checks"]["ai_services"]
    if ai_services.get("blocking") is not False:
        raise AssertionError("AI services must be non-blocking for installation readiness")
    if not ai_services["ready"]:
        degraded = set(payload["degraded_capabilities"])
        if not {"rag", "ai_assistants"}.issubset(degraded):
            raise AssertionError("missing AI services must degrade rag and ai_assistants")


def assert_upgrade_check_contract(payload: dict) -> None:
    if payload.get("plan") != "upgrade_check":
        raise AssertionError("upgrade-check must return plan=upgrade_check")
    if not isinstance(payload.get("ready"), bool):
        raise AssertionError("upgrade-check ready must be boolean")
    if not isinstance(payload.get("upgrade_required"), bool):
        raise AssertionError("upgrade_required must be boolean")
    if not isinstance(payload.get("safe_to_attempt_upgrade"), bool):
        raise AssertionError("safe_to_attempt_upgrade must be boolean")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("upgrade-check must not execute destructive action")
    if payload.get("migration_executed") is not False:
        raise AssertionError("upgrade-check must not run migrations")
    if not isinstance(payload.get("operator_action_required"), str) or not payload["operator_action_required"]:
        raise AssertionError("upgrade-check must return an operator action")
    if not isinstance(payload.get("checks"), dict):
        raise AssertionError("upgrade-check checks must be an object")
    assert_status_contract(payload["status"])

    required_checks = {"alembic", "database"}
    missing = sorted(required_checks - set(payload["checks"]))
    if missing:
        raise AssertionError(f"upgrade-check missing checks: {missing}")

    alembic = payload["checks"]["alembic"]
    for key in ("ready", "database_revision_known", "migration_required"):
        if not isinstance(alembic.get(key), bool):
            raise AssertionError(f"upgrade-check alembic {key} must be boolean")
    if not isinstance(alembic.get("known_revisions_count"), int):
        raise AssertionError("upgrade-check alembic known_revisions_count must be integer")

    database = payload["checks"]["database"]
    if not isinstance(database.get("ready"), bool):
        raise AssertionError("upgrade-check database ready must be boolean")
    if database.get("configuration", {}).get("name") != "DATABASE_URL":
        raise AssertionError("upgrade-check database configuration must describe DATABASE_URL")


def assert_rollback_check_contract(payload: dict) -> None:
    if payload.get("plan") != "rollback_check":
        raise AssertionError("rollback-check must return plan=rollback_check")
    if not isinstance(payload.get("ready"), bool):
        raise AssertionError("rollback-check ready must be boolean")
    if not isinstance(payload.get("safe_boundary_identified"), bool):
        raise AssertionError("safe_boundary_identified must be boolean")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("rollback-check must never execute destructive action")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("rollback-check must not run downgrades")
    if not isinstance(payload.get("operator_action_required"), str) or not payload["operator_action_required"]:
        raise AssertionError("rollback-check must return an operator action")
    if not isinstance(payload.get("checks"), dict):
        raise AssertionError("rollback-check checks must be an object")
    assert_status_contract(payload["status"])

    required_checks = {"alembic", "database"}
    missing = sorted(required_checks - set(payload["checks"]))
    if missing:
        raise AssertionError(f"rollback-check missing checks: {missing}")

    alembic = payload["checks"]["alembic"]
    for key in ("ready", "current_known", "target_known"):
        if not isinstance(alembic.get(key), bool):
            raise AssertionError(f"rollback-check alembic {key} must be boolean")
    if not isinstance(alembic.get("known_revisions_count"), int):
        raise AssertionError("rollback-check alembic known_revisions_count must be integer")

    database = payload["checks"]["database"]
    if not isinstance(database.get("ready"), bool):
        raise AssertionError("rollback-check database ready must be boolean")
    if database.get("configuration", {}).get("name") != "DATABASE_URL":
        raise AssertionError("rollback-check database configuration must describe DATABASE_URL")


def assert_readiness_check_contract(payload: dict) -> None:
    if payload.get("plan") != "readiness_check":
        raise AssertionError("readiness-check must return plan=readiness_check")
    if not isinstance(payload.get("ready"), bool):
        raise AssertionError("readiness-check ready must be boolean")
    if not isinstance(payload.get("blocking_checks"), list):
        raise AssertionError("readiness-check blocking_checks must be a list")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("readiness-check must never execute destructive action")
    if payload.get("migration_executed") is not False:
        raise AssertionError("readiness-check must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("readiness-check must not run downgrades")
    if not isinstance(payload.get("operator_action_required"), str) or not payload["operator_action_required"]:
        raise AssertionError("readiness-check must return an operator action")
    if not isinstance(payload.get("checks"), dict):
        raise AssertionError("readiness-check checks must be an object")
    if not isinstance(payload.get("profiles"), dict):
        raise AssertionError("readiness-check profiles must be an object")
    if not isinstance(payload.get("degraded_capabilities"), list):
        raise AssertionError("readiness-check degraded_capabilities must be a list")

    required_checks = {"install", "upgrade", "rollback"}
    missing = sorted(required_checks - set(payload["checks"]))
    if missing:
        raise AssertionError(f"readiness-check missing checks: {missing}")

    assert_install_check_contract(payload["install"])
    if payload["profiles"] != payload["install"]["profiles"]:
        raise AssertionError("readiness-check must propagate install profiles")
    if payload["degraded_capabilities"] != payload["install"]["degraded_capabilities"]:
        raise AssertionError("readiness-check must propagate degraded capabilities")
    assert_upgrade_check_contract(payload["upgrade"])
    if payload.get("rollback") is not None:
        assert_rollback_check_contract(payload["rollback"])


def assert_operation_decision_install_contract(payload: dict) -> None:
    if payload.get("plan") != "operation_decision":
        raise AssertionError("operation-decision must return plan=operation_decision")
    if payload.get("operation") != "install":
        raise AssertionError("operation-decision install must return operation=install")
    if payload.get("destructive_action_executed") is not False:
        raise AssertionError("operation-decision must never execute destructive action")
    if payload.get("migration_executed") is not False:
        raise AssertionError("operation-decision must not run migrations")
    if payload.get("downgrade_executed") is not False:
        raise AssertionError("operation-decision must not run downgrades")
    if payload.get("manual_approval_required") is not False:
        raise AssertionError("install operation must not require manual approval")

    readiness = payload.get("readiness")
    if not isinstance(readiness, dict):
        raise AssertionError("operation-decision must include readiness")
    assert_install_check_contract(readiness)

    document_ready = readiness["profiles"]["document_management"]["ready"]
    ai_ready = readiness["profiles"]["ai_services"]["ready"]
    if document_ready and not ai_ready and payload.get("decision") != "proceed":
        raise AssertionError("install must proceed when document_management is ready even if AI services are degraded")
    if not document_ready:
        if payload.get("decision") != "blocked":
            raise AssertionError("install must be blocked when document_management is not ready")
        if "install_readiness_blocked" not in payload.get("blocking_reasons", []):
            raise AssertionError("blocked install must report install_readiness_blocked")


def main() -> int:
    status = run_command("status")
    assert_status_contract(status)

    install = run_command("install-plan")
    if install.get("plan") != "install":
        raise AssertionError("install-plan must return plan=install")
    if not isinstance(install.get("steps"), list) or not install["steps"]:
        raise AssertionError("install-plan must return non-empty steps")
    assert_status_contract(install["status"])

    install_check = run_command("install-check")
    assert_install_check_contract(install_check)

    upgrade_check = run_command("upgrade-check")
    assert_upgrade_check_contract(upgrade_check)

    upgrade = run_command("pre-upgrade-check")
    if upgrade.get("plan") != "pre_upgrade_check":
        raise AssertionError("pre-upgrade-check must return plan=pre_upgrade_check")
    assert_status_contract(upgrade["status"])

    rollback_check = run_command("rollback-check", "--target-revision", "not_a_revision")
    assert_rollback_check_contract(rollback_check)
    if rollback_check.get("safe_boundary_identified") is not False:
        raise AssertionError("unknown target must not identify rollback-check safe boundary")

    rollback = run_command("rollback-plan", "--target-revision", "not_a_revision")
    if rollback.get("plan") != "rollback":
        raise AssertionError("rollback-plan must return plan=rollback")
    if rollback.get("destructive_action_executed") is not False:
        raise AssertionError("rollback-plan must never execute destructive action")
    if rollback.get("safe_boundary_identified") is not False:
        raise AssertionError("unknown target must not identify safe rollback boundary")
    assert_status_contract(rollback["status"])

    readiness = run_command("readiness-check")
    assert_readiness_check_contract(readiness)

    install_decision = run_command("operation-decision", "--operation", "install")
    assert_operation_decision_install_contract(install_decision)

    print(json.dumps({"passed": True, "checked": ["status", "install-plan", "install-check", "upgrade-check", "pre-upgrade-check", "rollback-check", "rollback-plan", "readiness-check", "operation-decision-install"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
