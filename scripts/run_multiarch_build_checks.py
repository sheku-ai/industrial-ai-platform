#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.process_runner import ProcessExecutionError, run_process

DEFAULT_PLATFORMS = ("linux/amd64", "linux/arm64")
TARGETS = {
    "api": PROJECT_ROOT / "apps/api",
    "portal": PROJECT_ROOT,
}
DOCKERFILES = {
    "api": PROJECT_ROOT / "apps/api/Dockerfile",
    "portal": PROJECT_ROOT / "apps/admin-portal/Dockerfile",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate API and portal builds for multiple container architectures."
    )
    parser.add_argument(
        "--platforms",
        default=",".join(DEFAULT_PLATFORMS),
        help="Comma-separated OCI platforms.",
    )
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--skip-portal", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser.parse_args()


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame) -> None:
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def parse_platforms(raw: str) -> list[str]:
    platforms = [item.strip() for item in raw.split(",") if item.strip()]
    if not platforms:
        raise ValueError("at least one platform is required")
    invalid = [item for item in platforms if not item.startswith("linux/")]
    if invalid:
        raise ValueError(f"unsupported non-Linux platforms: {', '.join(invalid)}")
    return list(dict.fromkeys(platforms))


def build_command(docker: str, target: str, platforms: list[str]) -> list[str]:
    command = [
        docker,
        "buildx",
        "build",
        "--platform",
        ",".join(platforms),
        "--file",
        str(DOCKERFILES[target]),
        "--output",
        "type=cacheonly",
    ]
    command.append(str(TARGETS[target]))
    return command


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2
    if args.skip_api and args.skip_portal:
        print("ERROR: both targets cannot be skipped", file=sys.stderr)
        return 2

    try:
        platforms = parse_platforms(args.platforms)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker executable was not found in PATH", file=sys.stderr)
        return 2

    install_signal_handlers()
    targets = [
        target
        for target in ("api", "portal")
        if not ((target == "api" and args.skip_api) or (target == "portal" and args.skip_portal))
    ]

    try:
        step("Validate Docker buildx")
        run_process(
            [docker, "buildx", "version"],
            cwd=PROJECT_ROOT,
            timeout_seconds=args.timeout_seconds,
        )

        for target in targets:
            step(f"Build {target} for {', '.join(platforms)}")
            run_process(
                build_command(docker, target, platforms),
                cwd=PROJECT_ROOT,
                timeout_seconds=args.timeout_seconds,
            )

        print(
            json.dumps(
                {
                    "passed": True,
                    "platforms": platforms,
                    "targets": targets,
                    "published": False,
                    "output": "cacheonly",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except KeyboardInterrupt:
        print("\nMulti-architecture build validation interrupted.", file=sys.stderr, flush=True)
        return 130
    except ProcessExecutionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        return exc.result.returncode or 1
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
