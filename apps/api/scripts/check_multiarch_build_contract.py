#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/run_multiarch_build_checks.py"
WRAPPER = ROOT / "scripts/run_multiarch_build_checks.ps1"
WORKFLOW = ROOT / ".github/workflows/container-portability.yml"


def contains_buildx_build(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.List | ast.Tuple):
            continue
        values = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if "buildx" in values and "build" in values:
            return True
    return False


def main() -> int:
    runner = RUNNER.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    tree = ast.parse(runner, filename=str(RUNNER))
    wrapper_lines = [line for line in wrapper.splitlines() if line.strip()]

    checks = {
        "required_files_exist": all(path.exists() for path in (RUNNER, WRAPPER, WORKFLOW)),
        "runner_uses_argparse": "argparse.ArgumentParser" in runner,
        "runner_defaults_to_amd64_and_arm64": 'DEFAULT_PLATFORMS = ("linux/amd64", "linux/arm64")' in runner,
        "runner_uses_buildx": contains_buildx_build(tree),
        "runner_does_not_publish": '"type=cacheonly"' in runner,
        "runner_builds_api": '"api": PROJECT_ROOT / "apps/api"' in runner,
        "runner_builds_portal": '"portal": PROJECT_ROOT' in runner,
        "runner_bootstraps_project_path": "sys.path.insert(0, str(PROJECT_ROOT))" in runner,
        "runner_handles_signals": "signal.SIGINT" in runner and "signal.SIGTERM" in runner,
        "runner_has_main_guard": any(isinstance(node, ast.If) for node in ast.walk(tree)),
        "wrapper_is_thin": len(wrapper_lines) <= 15,
        "wrapper_has_no_docker_logic": "docker " not in wrapper.lower(),
        "wrapper_invokes_python_runner": RUNNER.name in wrapper,
        "wrapper_propagates_exit_code": "exit $LASTEXITCODE" in wrapper,
        "workflow_is_manual_and_automatic": "workflow_dispatch:" in workflow
        and "pull_request:" in workflow
        and "push:" in workflow,
        "workflow_sets_up_qemu": "docker/setup-qemu-action@v3" in workflow,
        "workflow_sets_up_buildx": "docker/setup-buildx-action@v3" in workflow,
        "workflow_runs_static_contract": "check_container_portability_contract.py" in workflow,
        "workflow_runs_multiarch_runner": RUNNER.name in workflow,
        "workflow_targets_both_architectures": "linux/amd64,linux/arm64" in workflow,
        "workflow_does_not_push": "push: true" not in workflow.lower(),
    }
    result = {
        "stage": "multiarch_build_foundation",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
