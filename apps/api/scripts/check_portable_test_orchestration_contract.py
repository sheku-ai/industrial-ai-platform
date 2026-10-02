#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

RUNNER_NAMES = (
    "run_runtime_isolated_domain_tests",
    "run_ingestion_multimodal_isolated_tests",
    "run_database_only_persistent_writer_tests",
    "run_runtime_lease_domain_tests",
    "run_runtime_worker_domain_tests",
    "run_sprint_26_3_gate",
)
RUNNERS = {name: PROJECT_ROOT / "scripts" / f"{name}.py" for name in RUNNER_NAMES}
WRAPPERS = {name: PROJECT_ROOT / "scripts" / f"{name}.ps1" for name in RUNNER_NAMES}
PROCESS_HELPER = PROJECT_ROOT / "scripts" / "lib" / "process_runner.py"
COMPOSE_HELPER = PROJECT_ROOT / "scripts" / "lib" / "docker_compose.py"
ENVIRONMENT_HELPER = PROJECT_ROOT / "scripts" / "lib" / "environment_scope.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse(path: Path) -> ast.AST:
    return ast.parse(read(path), filename=str(path))


def subprocess_uses_list(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"run", "Popen"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.List | ast.Tuple | ast.Call | ast.Name):
            return False
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return False
    return True


def portable_runner_checks(prefix: str, text: str, tree: ast.AST) -> dict[str, bool]:
    windows_path_pattern = re.compile(r"(?:[A-Za-z]:\\|\\Users\\|\\projects\\)", re.IGNORECASE)
    bash_only_pattern = re.compile(r"\b(?:set -e|source |export |/bin/bash|\$\{BASH_SOURCE)")
    return {
        f"{prefix}_uses_argparse": "argparse.ArgumentParser" in text,
        f"{prefix}_supports_timeout": "--timeout-seconds" in text,
        f"{prefix}_supports_skip_build": "--skip-build" in text,
        f"{prefix}_uses_pathlib": "Path(" in text and "from pathlib import Path" in text,
        f"{prefix}_handles_sigint": "signal.SIGINT" in text,
        f"{prefix}_handles_sigterm": "signal.SIGTERM" in text,
        f"{prefix}_has_no_windows_absolute_paths": not windows_path_pattern.search(text),
        f"{prefix}_has_no_bash_only_commands": not bash_only_pattern.search(text),
        f"{prefix}_does_not_invoke_powershell": ".ps1" not in text and "powershell" not in text.lower(),
    }


def wrapper_checks(prefix: str, text: str, runner_name: str) -> dict[str, bool]:
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        f"{prefix}_is_thin": len(lines) <= 15,
        f"{prefix}_contains_no_compose_logic": "docker compose" not in text.lower(),
        f"{prefix}_invokes_python_runner": runner_name in text,
        f"{prefix}_propagates_exit_code": "exit $LASTEXITCODE" in text,
    }


def main() -> int:
    required = [*RUNNERS.values(), *WRAPPERS.values(), PROCESS_HELPER, COMPOSE_HELPER, ENVIRONMENT_HELPER]
    texts = {path: read(path) if path.exists() else "" for path in required}
    trees = {
        path: parse(path) if path.exists() and path.suffix == ".py" else ast.Module(body=[], type_ignores=[])
        for path in required
    }

    checks: dict[str, Any] = {"required_files_exist": all(path.exists() for path in required)}
    for name, runner in RUNNERS.items():
        prefix = name.removeprefix("run_")
        checks.update(portable_runner_checks(prefix, texts[runner], trees[runner]))
        checks.update(wrapper_checks(f"{prefix}_wrapper", texts[WRAPPERS[name]], runner.name))

    runtime_text = texts[RUNNERS["run_runtime_isolated_domain_tests"]]
    ingestion_text = texts[RUNNERS["run_ingestion_multimodal_isolated_tests"]]
    database_text = texts[RUNNERS["run_database_only_persistent_writer_tests"]]
    lease_text = texts[RUNNERS["run_runtime_lease_domain_tests"]]
    worker_text = texts[RUNNERS["run_runtime_worker_domain_tests"]]
    gate_text = texts[RUNNERS["run_sprint_26_3_gate"]]
    process_text = texts[PROCESS_HELPER]
    compose_text = texts[COMPOSE_HELPER]
    environment_text = texts[ENVIRONMENT_HELPER]

    database_checks = (
        "check_multimodal_retrieval_postgres_e2e.py",
        "check_processing_revision_selection_e2e.py",
        "check_visual_chunk_concurrency_e2e.py",
        "check_visual_chunk_revision_idempotency_e2e.py",
    )
    lease_checks = (
        "check_runtime_lease_retry_e2e.py",
        "check_runtime_lease_exhaustion_e2e.py",
        "check_runtime_lease_invalid_payload_e2e.py",
        "check_runtime_lease_concurrency_e2e.py",
    )
    worker_checks = (
        "check_runtime_worker_control_e2e.py",
        "check_runtime_worker_health_e2e.py",
        "check_runtime_worker_readiness_api_e2e.py",
        "check_runtime_worker_command_audit_e2e.py",
        "check_runtime_worker_stale_audit_e2e.py",
        "check_runtime_worker_history_api_e2e.py",
        "check_runtime_worker_summary_e2e.py",
    )

    checks.update(
        {
            "runtime_runner_supports_skip_portal_build": "--skip-portal-build" in runtime_text,
            "runtime_runner_uses_current_python": "sys.executable" in runtime_text,
            "ingestion_runner_supports_startup_delay": "--startup-delay-seconds" in ingestion_text,
            "ingestion_runner_uses_multiple_compose_files": "docker-compose.test.yml" in ingestion_text
            and "docker-compose.ingestion-test.yml" in ingestion_text,
            "ingestion_runner_generates_ephemeral_credentials": 'ensure_ephemeral("TEST_MINIO_ACCESS_KEY"'
            in ingestion_text
            and 'ensure_ephemeral("TEST_MINIO_SECRET_KEY"' in ingestion_text,
            "ingestion_runner_restores_environment": "with EnvironmentScope()" in ingestion_text,
            "ingestion_runner_waits_for_services": '"--wait"' in ingestion_text,
            "ingestion_runner_collects_diagnostics": "compose.diagnostic_logs" in ingestion_text,
            "database_runner_uses_test_compose": "docker-compose.test.yml" in database_text,
            "database_runner_executes_all_checks": all(name in database_text for name in database_checks),
            "database_runner_migrates_once": database_text.count('compose.run(["run", "--rm", "migrator-test"])') == 1,
            "database_runner_collects_diagnostics": "compose.diagnostic_logs" in database_text,
            "lease_runner_executes_all_checks": all(name in lease_text for name in lease_checks),
            "lease_runner_collects_diagnostics": "compose.diagnostic_logs" in lease_text,
            "worker_runner_executes_all_checks": all(name in worker_text for name in worker_checks),
            "worker_runner_collects_diagnostics": "compose.diagnostic_logs" in worker_text,
            "gate_runner_supports_skip_portal_build": "--skip-portal-build" in gate_text,
            "gate_runner_supports_health_timeout": "--health-timeout-seconds" in gate_text,
            "gate_runner_uses_ingestion_profile": 'profiles=["ingestion"]' in gate_text,
            "gate_runner_invokes_python_domain_runners": "run_runtime_isolated_domain_tests.py" in gate_text
            and "run_ingestion_multimodal_isolated_tests.py" in gate_text,
            "gate_runner_does_not_invoke_powershell_runners": ".ps1" not in gate_text,
            "gate_runner_checks_persistent_test_count": "baseline = count_test_organizations" in gate_text
            and "final_count = count_test_organizations" in gate_text,
            "gate_runner_fails_on_persistent_growth": "Persistent test organization count changed during gate"
            in gate_text,
            "gate_runner_waits_for_managed_services": "wait_managed_services_healthy" in gate_text,
            "gate_runner_builds_portal_portably": '["npm", "run", "build"]' in gate_text,
            "process_helper_uses_subprocess_lists": subprocess_uses_list(trees[PROCESS_HELPER]),
            "process_helper_disables_shell_execution": "shell=True" not in process_text,
            "compose_helper_detects_docker": 'shutil.which("docker")' in compose_text,
            "compose_helper_detects_compose_v2": '[docker, "compose", "version"]' in compose_text,
            "compose_helper_supports_multiple_files": "compose_files" in compose_text,
            "compose_helper_supports_profiles": "profiles" in compose_text,
            "compose_helper_propagates_timeouts": "timeout_seconds" in compose_text,
            "environment_scope_generates_ephemeral_credentials": "secrets.choice" in environment_text,
            "environment_scope_restores_variables": "self._previous" in environment_text
            and "os.environ.pop" in environment_text,
        }
    )

    passed = all(bool(value) for value in checks.values())
    result = {
        "stage": "portable_orchestration_stage_5",
        "passed": passed,
        "checks": checks,
        "deferred": [],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
