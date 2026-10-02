#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.test.yml",
    ROOT / "docker-compose.ingestion-test.yml",
)
FILES = (
    *COMPOSE_FILES,
    ROOT / "apps/api/Dockerfile",
    ROOT / "apps/admin-portal/Dockerfile",
    ROOT / "apps/api/requirements.txt",
)


def has_compose_platform_override(text: str) -> bool:
    return any(re.match(r"^\s{4}platform\s*:", line, flags=re.IGNORECASE) is not None for line in text.splitlines())


def main() -> int:
    texts = {path: path.read_text(encoding="utf-8") for path in FILES}
    combined = "\n".join(texts.values())
    architecture_pin = re.compile(r"(?:linux/)?(?:amd64|x86_64|arm64|aarch64)", re.IGNORECASE)

    api_dockerfile = texts[ROOT / "apps/api/Dockerfile"]
    portal_dockerfile = texts[ROOT / "apps/admin-portal/Dockerfile"]
    compose = texts[ROOT / "docker-compose.yml"]
    requirements = texts[ROOT / "apps/api/requirements.txt"]

    checks = {
        "required_files_exist": all(path.exists() for path in FILES),
        "no_architecture_pins": architecture_pin.search(combined) is None,
        "compose_has_no_platform_override": not any(
            has_compose_platform_override(texts[path]) for path in COMPOSE_FILES
        ),
        "api_uses_official_python_base": api_dockerfile.startswith("FROM python:"),
        "portal_uses_official_node_base": portal_dockerfile.startswith("FROM node:"),
        "api_runs_as_non_root": "USER platform" in api_dockerfile,
        "portal_runs_as_non_root": "USER platform" in portal_dockerfile,
        "api_uses_exec_form_command": 'CMD ["uvicorn"' in api_dockerfile,
        "portal_uses_exec_form_command": 'CMD ["node", "apps/admin-portal/server.js"]' in portal_dockerfile,
        "compose_builds_api_from_shared_context": "x-api-build:" in compose and "context: ./apps/api" in compose,
        "postgres_uses_official_multiarch_image": "image: postgres:16" in compose,
        "redis_uses_official_multiarch_image": "image: redis:7.4-alpine" in compose,
        "python_dependencies_have_no_direct_wheel_urls": "https://" not in requirements
        and "http://" not in requirements,
        "python_dependencies_have_no_local_paths": not any(
            line.strip().startswith(("./", "../", "/"))
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
    }
    result = {
        "stage": "container_portability_foundation",
        "passed": all(checks.values()),
        "checks": checks,
        "files": [str(path.relative_to(ROOT)) for path in FILES],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
