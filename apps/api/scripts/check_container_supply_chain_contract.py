#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BAKE = ROOT / "docker-bake.hcl"
POLICY = ROOT / "config/container-release-policy.json"
WORKFLOW = ROOT / ".github/workflows/container-portability.yml"


def main() -> int:
    bake = BAKE.read_text(encoding="utf-8")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")

    checks = {
        "required_files_exist": all(path.exists() for path in (BAKE, POLICY, WORKFLOW)),
        "publication_disabled_by_default": policy.get("publication_enabled") is False,
        "manual_approval_required": policy.get("manual_approval_required") is True,
        "latest_tag_disallowed": policy.get("latest_tag_allowed") is False,
        "required_targets_are_generic": policy.get("required_targets") == ["api", "portal"],
        "required_platforms_are_multiarch": policy.get("required_platforms") == ["linux/amd64", "linux/arm64"],
        "sbom_required_by_policy": "sbom" in policy.get("required_attestations", []),
        "provenance_required_by_policy": "provenance" in policy.get("required_attestations", []),
        "max_provenance_required": policy.get("required_provenance_mode") == "max",
        "bake_enables_sbom": '"type=sbom"' in bake,
        "bake_enables_max_provenance": '"type=provenance,mode=max"' in bake,
        "bake_has_no_latest_tag": ":latest" not in bake,
        "workflow_has_read_only_permissions": "contents: read" in workflow,
        "workflow_has_no_package_write_permission": "packages: write" not in workflow,
        "workflow_has_no_registry_login": "docker/login-action" not in workflow,
        "workflow_has_no_push": "--push" not in workflow and "push: true" not in workflow.lower(),
    }
    result = {
        "stage": "container_supply_chain_foundation",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
