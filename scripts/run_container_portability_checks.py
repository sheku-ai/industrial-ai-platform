#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import shutil
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.docker_compose import DockerCompose, DockerComposeUnavailableError
from scripts.lib.process_runner import ProcessExecutionError, run_process

SERVICES = ("api", "portal")
API_SMOKE_SCRIPT = """
import importlib
import json
import os
from pathlib import Path

modules = [
    "fastapi",
    "sqlalchemy",
    "pypdf",
    "fitz",
    "PIL",
    "reportlab",
    "openpyxl",
    "boto3",
    "redis",
]
for module in modules:
    importlib.import_module(module)

runtime_dir = Path("/app/runtime")
probe = runtime_dir / ".image-smoke"
probe.write_text("ok", encoding="utf-8")
probe.unlink()

result = {
    "imports": modules,
    "runtime_directory_writable": True,
    "uid": os.getuid(),
    "non_root": os.getuid() != 0,
    "expected_uid": os.getuid() == 10001,
}
print(json.dumps(result, sort_keys=True))
if not result["non_root"] or not result["expected_uid"]:
    raise SystemExit(1)
""".strip()
PORTAL_SMOKE_SCRIPT = """
const fs = require("fs");

const uid = typeof process.getuid === "function" ? process.getuid() : null;
const result = {
  uid,
  non_root: uid !== 0,
  expected_uid: uid === 10001,
  server_entrypoint_present: fs.existsSync("/app/apps/admin-portal/server.js"),
  static_assets_present: fs.existsSync("/app/apps/admin-portal/.next/static"),
};
console.log(JSON.stringify(result));
if (!Object.values(result).every(Boolean)) {
  process.exit(1);
}
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate container portability and native Docker image architecture."
    )
    parser.add_argument("--skip-build", action="store_true", help="Inspect existing images without rebuilding.")
    parser.add_argument("--skip-portal", action="store_true", help="Validate only the API image.")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame) -> None:
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def normalize_architecture(value: str) -> str:
    aliases = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    return aliases.get(value.strip().lower(), value.strip().lower())


def inspect_image_architecture(docker: str, image_reference: str, timeout_seconds: int) -> str:
    result = run_process(
        [docker, "image", "inspect", image_reference, "--format", "{{json .Architecture}}"],
        cwd=PROJECT_ROOT,
        timeout_seconds=timeout_seconds,
        stream=False,
    )
    return str(json.loads(result.stdout.strip()))


def smoke_api_image(docker: str, image_reference: str, timeout_seconds: int) -> dict[str, object]:
    python_result = run_process(
        [docker, "run", "--rm", "--entrypoint", "python", image_reference, "-c", API_SMOKE_SCRIPT],
        cwd=PROJECT_ROOT,
        timeout_seconds=timeout_seconds,
        stream=False,
    )
    payload = json.loads(python_result.stdout.strip().splitlines()[-1])
    if not isinstance(payload, dict):
        raise RuntimeError("API image smoke did not return a JSON object")

    tesseract_result = run_process(
        [docker, "run", "--rm", "--entrypoint", "tesseract", image_reference, "--version"],
        cwd=PROJECT_ROOT,
        timeout_seconds=timeout_seconds,
        stream=False,
    )
    version_line = next(
        (line.strip() for line in tesseract_result.stdout.splitlines() if line.strip()),
        "",
    )
    if not version_line.lower().startswith("tesseract"):
        raise RuntimeError("API image smoke could not verify Tesseract")

    payload["tesseract_available"] = True
    payload["tesseract_version"] = version_line
    return payload


def smoke_portal_image(docker: str, image_reference: str, timeout_seconds: int) -> dict[str, object]:
    container_name = f"industrial-ai-portal-smoke-{os.getpid()}"
    try:
        run_process(
            [
                docker,
                "run",
                "--detach",
                "--name",
                container_name,
                "--publish",
                "127.0.0.1::3000",
                image_reference,
            ],
            cwd=PROJECT_ROOT,
            timeout_seconds=timeout_seconds,
            stream=False,
        )

        port_result = run_process(
            [docker, "port", container_name, "3000/tcp"],
            cwd=PROJECT_ROOT,
            timeout_seconds=timeout_seconds,
            stream=False,
        )
        binding = next((line.strip() for line in port_result.stdout.splitlines() if line.strip()), "")
        if not binding or ":" not in binding:
            raise RuntimeError("Portal image smoke could not resolve the published port")
        host_port = int(binding.rsplit(":", 1)[1])
        url = f"http://127.0.0.1:{host_port}/"

        status_code: int | None = None
        deadline = time.monotonic() + min(timeout_seconds, 45)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    status_code = int(response.status)
                    break
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionResetError,
                http.client.RemoteDisconnected,
            ) as exc:
                last_error = exc
                time.sleep(1)
        if status_code is None:
            raise RuntimeError(f"Portal image did not become HTTP-ready: {last_error}")

        node_result = run_process(
            [docker, "exec", container_name, "node", "-e", PORTAL_SMOKE_SCRIPT],
            cwd=PROJECT_ROOT,
            timeout_seconds=timeout_seconds,
            stream=False,
        )
        payload = json.loads(node_result.stdout.strip().splitlines()[-1])
        if not isinstance(payload, dict):
            raise RuntimeError("Portal image smoke did not return a JSON object")
        payload["http_ready"] = 200 <= status_code < 400
        payload["http_status"] = status_code
        if not payload["http_ready"]:
            raise RuntimeError(f"Portal image returned unexpected HTTP status: {status_code}")
        return payload
    finally:
        try:
            run_process(
                [docker, "rm", "--force", container_name],
                cwd=PROJECT_ROOT,
                timeout_seconds=min(timeout_seconds, 30),
                stream=False,
            )
        except Exception:
            pass


def compose_image_references(compose: DockerCompose) -> dict[str, str]:
    result = compose.run(["config", "--format", "json"], stream=False)
    model = json.loads(result.stdout)
    services = model.get("services", {})
    if not isinstance(services, dict):
        raise RuntimeError("Compose configuration did not contain a services mapping")

    project_name = str(model.get("name", "")).strip()
    if not project_name:
        raise RuntimeError("Compose configuration did not contain a project name")

    references: dict[str, str] = {}
    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue
        image = str(service_config.get("image", "")).strip()
        if image:
            references[str(service_name)] = image
            continue
        if service_config.get("build") is not None:
            references[str(service_name)] = f"{project_name}-{service_name}:latest"
    return references


def run_contract(relative_path: str, timeout_seconds: int) -> None:
    run_process(
        [sys.executable, str(PROJECT_ROOT / relative_path)],
        cwd=PROJECT_ROOT,
        timeout_seconds=timeout_seconds,
    )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2

    install_signal_handlers()
    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker executable was not found in PATH", file=sys.stderr)
        return 2

    services = ["api"] if args.skip_portal else list(SERVICES)
    host_architecture = normalize_architecture(platform.machine())

    try:
        compose = DockerCompose(
            project_root=PROJECT_ROOT,
            compose_files=[PROJECT_ROOT / "docker-compose.yml"],
            timeout_seconds=args.timeout_seconds,
        )
    except DockerComposeUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        step("Container portability contract")
        run_contract("apps/api/scripts/check_container_portability_contract.py", args.timeout_seconds)

        step("OCI artifact contract")
        run_contract("apps/api/scripts/check_local_oci_artifact_contract.py", args.timeout_seconds)

        step("API production image contract")
        run_contract("apps/api/scripts/check_api_production_image_contract.py", args.timeout_seconds)

        if not args.skip_portal:
            step("Portal production image contract")
            run_contract("apps/api/scripts/check_portal_production_image_contract.py", args.timeout_seconds)

        step("Validate Compose model")
        compose.run(["config", "--quiet"])

        if not args.skip_build:
            step("Build native container images")
            compose.run(["build", *services])

        image_references = compose_image_references(compose)
        inspected: dict[str, str] = {}
        for service in services:
            step(f"Inspect {service} image architecture")
            image_reference = image_references.get(service)
            if not image_reference:
                raise RuntimeError(f"Compose configuration has no image reference for service {service}")
            architecture = normalize_architecture(
                inspect_image_architecture(docker, image_reference, args.timeout_seconds)
            )
            inspected[service] = architecture
            if architecture != host_architecture:
                raise RuntimeError(
                    f"service {service} image architecture mismatch: "
                    f"host={host_architecture} image={architecture}"
                )

        api_image = image_references.get("api")
        if not api_image:
            raise RuntimeError("Compose configuration has no image reference for service api")
        step("API production image runtime smoke")
        api_runtime_smoke = smoke_api_image(docker, api_image, args.timeout_seconds)
        print(json.dumps(api_runtime_smoke, indent=2, sort_keys=True))

        portal_runtime_smoke: dict[str, object] | None = None
        if not args.skip_portal:
            portal_image = image_references.get("portal")
            if not portal_image:
                raise RuntimeError("Compose configuration has no image reference for service portal")
            step("Portal production image runtime smoke")
            portal_runtime_smoke = smoke_portal_image(docker, portal_image, args.timeout_seconds)
            print(json.dumps(portal_runtime_smoke, indent=2, sort_keys=True))

        payload = {
            "passed": True,
            "host_architecture": host_architecture,
            "images": inspected,
            "services": services,
            "api_runtime_smoke": api_runtime_smoke,
        }
        if portal_runtime_smoke is not None:
            payload["portal_runtime_smoke"] = portal_runtime_smoke
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("\nContainer portability validation interrupted.", file=sys.stderr, flush=True)
        return 130
    except ProcessExecutionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr, flush=True)
        return exc.result.returncode or 1
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
