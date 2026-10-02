#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BAKE = ROOT / "docker-bake.hcl"
RUNNER = ROOT / "scripts/run_container_release_plan.py"
WRAPPER = ROOT / "scripts/run_container_release_plan.ps1"


def main() -> int:
    bake = BAKE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    wrapper_lines = [line for line in wrapper.splitlines() if line.strip()]
    checks = {
        "required_files_exist": all(path.exists() for path in (BAKE, RUNNER, WRAPPER)),
        "bake_defines_api": 'target "api"' in bake,
        "bake_defines_portal": 'target "portal"' in bake,
        "bake_targets_amd64": "linux/amd64" in bake,
        "bake_targets_arm64": "linux/arm64" in bake,
        "bake_has_oci_version_label": "org.opencontainers.image.version" in bake,
        "bake_has_oci_revision_label": "org.opencontainers.image.revision" in bake,
        "bake_has_oci_created_label": "org.opencontainers.image.created" in bake,
        "runner_uses_buildx_bake": "buildx" in runner and "bake" in runner,
        "runner_uses_print_only": "--print" in runner,
        "runner_does_not_publish": '"published": False' in runner,
        "runner_validates_api_and_portal": 'for target_name in ("api", "portal")' in runner,
        "wrapper_is_thin": len(wrapper_lines) <= 15,
        "wrapper_has_no_docker_logic": "docker " not in wrapper.lower(),
        "wrapper_invokes_python_runner": RUNNER.name in wrapper,
        "wrapper_propagates_exit_code": "exit $LASTEXITCODE" in wrapper,
    }
    result = {
        "stage": "container_release_plan_contract",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
