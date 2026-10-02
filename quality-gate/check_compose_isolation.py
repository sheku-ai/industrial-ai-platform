#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.quality.yml"
PROJECT = "industrial-ai-quality"
DATABASE_SERVICES = {"quality-platform-postgres", "quality-identity-postgres"}
EGRESS_SERVICES = {"quality-npm-audit", "quality-python-audit"}


def main() -> int:
    completed = subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        print(json.dumps({"passed": False, "error": "docker compose config failed"}, indent=2))
        return completed.returncode or 1

    model = json.loads(completed.stdout)
    services = model.get("services", {})
    networks = model.get("networks", {})
    volumes = model.get("volumes", {})
    serialized = json.dumps(model)
    source = COMPOSE_FILE.read_text(encoding="utf-8")
    egress_connected = {
        name
        for name, service in services.items()
        if "quality-egress" in set(service.get("networks", {}))
    }

    checks = {
        "fixed_project_name": model.get("name") == PROJECT,
        "no_published_ports": all(not service.get("ports") for service in services.values()),
        "no_preproduction_reference": "industrial-ai-clean" not in serialized and "industrial-ai-clean" not in source,
        "no_external_volumes": not volumes
        or all(not bool(configuration.get("external")) for configuration in volumes.values()),
        "no_env_file": "env_file:" not in source,
        "no_docker_socket": "/var/run/docker.sock" not in serialized and "/var/run/docker.sock" not in source,
        "no_privileged_service": all(not bool(service.get("privileged")) for service in services.values()),
        "database_network_internal": bool(networks.get("quality-database", {}).get("internal")),
        "databases_only_on_internal_network": all(
            set(services[name].get("networks", {})) == {"quality-database"} for name in DATABASE_SERVICES
        ),
        "databases_use_tmpfs": all(
            "/var/lib/postgresql/data" in services[name].get("tmpfs", []) for name in DATABASE_SERVICES
        ),
        "no_repository_bind_mounts": all(not service.get("volumes") for service in services.values()),
        "egress_only_for_audits": egress_connected == EGRESS_SERVICES,
        "portal_validator_has_no_network": services["quality-portal"].get("network_mode") == "none",
        "image_contracts_have_no_network": services["quality-image-contracts"].get("network_mode") == "none",
    }
    payload = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
