#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "release-artifacts"
TARGETS = ("api", "portal")
REQUIRED_PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}
ATTESTATION_REFERENCE_TYPE = "attestation-manifest"
OCI_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MIB = 1024 * 1024
DEFAULT_API_MAX_SIZE_MIB = 400
DEFAULT_PORTAL_MAX_SIZE_MIB = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and inspect local multi-architecture OCI artifacts without publishing them."
    )
    parser.add_argument("--version", default="1.3.1")
    parser.add_argument("--revision", default="local")
    parser.add_argument("--registry", default="ghcr.io")
    parser.add_argument("--namespace", default="industrial-ai-platform")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--skip-portal", action="store_true")
    parser.add_argument("--api-max-size-mib", type=int, default=DEFAULT_API_MAX_SIZE_MIB)
    parser.add_argument("--portal-max-size-mib", type=int, default=DEFAULT_PORTAL_MAX_SIZE_MIB)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    return parser.parse_args()


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame) -> None:
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def run(command: list[str], *, env: dict[str, str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    return result


def read_json_member(archive: tarfile.TarFile, member_name: str) -> dict[str, Any]:
    try:
        member = archive.getmember(member_name)
    except KeyError as exc:
        raise RuntimeError(f"OCI archive member not found: {member_name}") from exc
    extracted = archive.extractfile(member)
    if extracted is None:
        raise RuntimeError(f"OCI archive member is not readable: {member_name}")
    payload = json.load(extracted)
    if not isinstance(payload, dict):
        raise RuntimeError(f"OCI JSON member must contain an object: {member_name}")
    return payload


def blob_member_name(digest: str) -> str:
    algorithm, separator, encoded = digest.partition(":")
    if not separator or not algorithm or not encoded:
        raise RuntimeError(f"invalid OCI digest: {digest}")
    return f"blobs/{algorithm}/{encoded}"


def collect_oci_descriptors(
    archive: tarfile.TarFile,
    document: dict[str, Any],
    *,
    visited_digests: set[str],
) -> list[dict[str, Any]]:
    manifests = document.get("manifests", [])
    if not isinstance(manifests, list):
        raise RuntimeError("OCI index manifests must be a list")

    collected: list[dict[str, Any]] = []
    for descriptor in manifests:
        if not isinstance(descriptor, dict):
            continue
        collected.append(descriptor)

        media_type = str(descriptor.get("mediaType", "")).strip()
        digest = str(descriptor.get("digest", "")).strip()
        if media_type not in OCI_INDEX_MEDIA_TYPES or not digest or digest in visited_digests:
            continue

        visited_digests.add(digest)
        nested_document = read_json_member(archive, blob_member_name(digest))
        collected.extend(
            collect_oci_descriptors(
                archive,
                nested_document,
                visited_digests=visited_digests,
            )
        )
    return collected


def inspect_oci_archive(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"OCI artifact was not created or is empty: {path}")

    with tarfile.open(path, mode="r:*") as archive:
        root_index = read_json_member(archive, "index.json")
        descriptors = collect_oci_descriptors(
            archive,
            root_index,
            visited_digests=set(),
        )

    platforms: set[tuple[str, str]] = set()
    attestation_count = 0
    for descriptor in descriptors:
        platform_data = descriptor.get("platform", {})
        if isinstance(platform_data, dict):
            os_name = str(platform_data.get("os", "")).strip()
            architecture = str(platform_data.get("architecture", "")).strip()
            if os_name and architecture and (os_name, architecture) != ("unknown", "unknown"):
                platforms.add((os_name, architecture))

        annotations = descriptor.get("annotations", {})
        if isinstance(annotations, dict) and annotations.get("vnd.docker.reference.type") == ATTESTATION_REFERENCE_TYPE:
            attestation_count += 1

    missing_platforms = sorted(REQUIRED_PLATFORMS - platforms)
    if missing_platforms:
        raise RuntimeError(f"OCI artifact {path.name} is missing platforms: {missing_platforms}")
    if attestation_count < len(REQUIRED_PLATFORMS):
        raise RuntimeError(
            f"OCI artifact {path.name} has insufficient attestation manifests: {attestation_count}"
        )

    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "platforms": [f"{os_name}/{architecture}" for os_name, architecture in sorted(platforms)],
        "attestation_manifests": attestation_count,
        "manifest_descriptors": len(descriptors),
    }


def enforce_size_budget(target: str, artifact: dict[str, object], max_size_mib: int) -> None:
    max_size_bytes = max_size_mib * MIB
    size_bytes = int(artifact["size_bytes"])
    artifact["size_budget_bytes"] = max_size_bytes
    artifact["size_budget_mib"] = max_size_mib
    artifact["within_size_budget"] = size_bytes <= max_size_bytes
    if size_bytes > max_size_bytes:
        raise RuntimeError(
            f"OCI artifact {target} exceeds size budget: "
            f"actual={size_bytes} bytes budget={max_size_bytes} bytes"
        )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2
    if args.api_max_size_mib <= 0 or args.portal_max_size_mib <= 0:
        print("ERROR: artifact size budgets must be positive", file=sys.stderr)
        return 2
    if args.skip_api and args.skip_portal:
        print("ERROR: both targets cannot be skipped", file=sys.stderr)
        return 2

    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker executable was not found in PATH", file=sys.stderr)
        return 2

    install_signal_handlers()
    targets = [
        target
        for target in TARGETS
        if not ((target == "api" and args.skip_api) or (target == "portal" and args.skip_portal))
    ]
    size_budgets_mib = {
        "api": args.api_max_size_mib,
        "portal": args.portal_max_size_mib,
    }

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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

    artifacts: dict[str, dict[str, object]] = {}
    try:
        step("Validate Docker buildx")
        version_result = run(
            [docker, "buildx", "version"],
            env=env,
            timeout_seconds=args.timeout_seconds,
        )
        if version_result.returncode != 0:
            return version_result.returncode or 1

        for target in targets:
            artifact_path = output_dir / f"industrial-ai-platform-{target}-{args.version}-{args.revision}.oci.tar"
            if artifact_path.exists():
                artifact_path.unlink()

            step(f"Build local OCI artifact: {target}")
            build_result = run(
                [
                    docker,
                    "buildx",
                    "bake",
                    "--file",
                    "docker-bake.hcl",
                    "--set",
                    f"{target}.output=type=oci,dest={artifact_path}",
                    target,
                ],
                env=env,
                timeout_seconds=args.timeout_seconds,
            )
            if build_result.returncode != 0:
                return build_result.returncode or 1

            step(f"Inspect local OCI artifact: {target}")
            artifact = inspect_oci_archive(artifact_path)
            enforce_size_budget(target, artifact, size_budgets_mib[target])
            artifacts[target] = artifact

        payload = {
            "stage": "local_oci_artifact_build",
            "passed": True,
            "published": False,
            "version": args.version,
            "revision": args.revision,
            "created": created,
            "artifacts": artifacts,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("\nLocal OCI artifact build interrupted.", file=sys.stderr, flush=True)
        return 130
    except subprocess.TimeoutExpired as exc:
        print(f"ERROR: command timed out after {exc.timeout} seconds", file=sys.stderr)
        return 124
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
