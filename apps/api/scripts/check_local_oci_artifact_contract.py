#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/run_local_oci_artifact_build.py"
WRAPPER = ROOT / "scripts/run_local_oci_artifact_build.ps1"
BAKE = ROOT / "docker-bake.hcl"


def main() -> int:
    runner = RUNNER.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    bake = BAKE.read_text(encoding="utf-8")
    tree = ast.parse(runner, filename=str(RUNNER))
    wrapper_lines = [line for line in wrapper.splitlines() if line.strip()]

    checks = {
        "required_files_exist": all(path.exists() for path in (RUNNER, WRAPPER, BAKE)),
        "runner_uses_argparse": "argparse.ArgumentParser" in runner,
        "runner_uses_buildx_bake": '"buildx"' in runner and '"bake"' in runner,
        "runner_exports_oci": "type=oci" in runner,
        "runner_builds_api_and_portal": 'TARGETS = ("api", "portal")' in runner,
        "runner_checks_amd64": '("linux", "amd64")' in runner,
        "runner_checks_arm64": '("linux", "arm64")' in runner,
        "runner_checks_attestations": "attestation-manifest" in runner,
        "runner_does_not_publish": '"published": False' in runner,
        "runner_uses_runtime_artifact_dir": '"runtime" / "release-artifacts"' in runner,
        "runner_has_main_guard": any(isinstance(node, ast.If) for node in ast.walk(tree)),
        "runner_has_api_size_budget": "--api-max-size-mib" in runner,
        "runner_has_portal_size_budget": "--portal-max-size-mib" in runner,
        "runner_enforces_size_budget": "enforce_size_budget" in runner,
        "runner_reports_size_budget": '"within_size_budget"' in runner,
        "size_budgets_are_configurable": "args.api_max_size_mib" in runner and "args.portal_max_size_mib" in runner,
        "wrapper_is_thin": len(wrapper_lines) <= 15,
        "wrapper_has_no_docker_logic": "docker " not in wrapper.lower(),
        "wrapper_invokes_python_runner": RUNNER.name in wrapper,
        "wrapper_propagates_exit_code": "exit $LASTEXITCODE" in wrapper,
        "bake_enables_sbom": '"type=sbom"' in bake,
        "bake_enables_provenance": '"type=provenance,mode=max"' in bake,
    }
    result = {
        "stage": "local_oci_artifact_contract",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
