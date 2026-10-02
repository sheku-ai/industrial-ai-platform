#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]

DEFAULT_REGISTRY = "ghcr.io"
DEFAULT_NAMESPACE = "industrial-ai-platform"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render and validate the multi-architecture container release plan without publishing images."
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--version", default="1.6.0")
    parser.add_argument("--revision", default="local")
    parser.add_argument("--created", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def run(command: list[str], *, env: dict[str, str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def validate_plan(plan: dict[str, object], registry: str, namespace: str, version: str, revision: str) -> dict[str, bool]:
    targets = plan.get("target", {})
    if not isinstance(targets, dict):
        targets = {}

    expected_platforms = ["linux/amd64", "linux/arm64"]
    checks: dict[str, bool] = {
        "api_target_present": "api" in targets,
        "portal_target_present": "portal" in targets,
    }

    for target_name in ("api", "portal"):
        target = targets.get(target_name, {}) if isinstance(targets, dict) else {}
        if not isinstance(target, dict):
            target = {}
        tags = target.get("tags", [])
        platforms = target.get("platforms", [])
        labels = target.get("labels", {})
        expected_prefix = f"{registry}/{namespace}/{target_name}:"
        checks[f"{target_name}_has_version_tag"] = f"{expected_prefix}{version}" in tags
        checks[f"{target_name}_has_revision_tag"] = f"{expected_prefix}{revision}" in tags
        checks[f"{target_name}_targets_both_architectures"] = platforms == expected_platforms
        checks[f"{target_name}_has_version_label"] = isinstance(labels, dict) and labels.get("org.opencontainers.image.version") == version
        checks[f"{target_name}_has_revision_label"] = isinstance(labels, dict) and labels.get("org.opencontainers.image.revision") == revision
        checks[f"{target_name}_has_created_label"] = isinstance(labels, dict) and bool(labels.get("org.opencontainers.image.created"))

    return checks


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2

    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker executable was not found in PATH", file=sys.stderr)
        return 2

    created = args.created or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    env = os.environ.copy()
    env.update(
        {
            "REGISTRY": args.registry,
            "NAMESPACE": args.namespace,
            "VERSION": args.version,
            "REVISION": args.revision,
            "CREATED": created,
        }
    )

    result = run(
        [docker, "buildx", "bake", "--file", "docker-bake.hcl", "--print"],
        env=env,
        timeout_seconds=args.timeout_seconds,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        print(f"ERROR: docker buildx bake --print failed: {detail}", file=sys.stderr)
        return result.returncode or 1

    try:
        plan = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid buildx bake JSON: {exc}", file=sys.stderr)
        return 1

    checks = validate_plan(plan, args.registry, args.namespace, args.version, args.revision)
    payload = {
        "stage": "container_release_plan",
        "passed": all(checks.values()),
        "checks": checks,
        "registry": args.registry,
        "namespace": args.namespace,
        "version": args.version,
        "revision": args.revision,
        "created": created,
        "published": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
