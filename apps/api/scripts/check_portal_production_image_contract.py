#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "apps/admin-portal/Dockerfile"
NEXT_CONFIG = ROOT / "apps/admin-portal/next.config.ts"
BAKE = ROOT / "docker-bake.hcl"


def main() -> int:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    next_config = NEXT_CONFIG.read_text(encoding="utf-8")
    bake = BAKE.read_text(encoding="utf-8")

    proxy_route = (ROOT / "apps/admin-portal/app/api/[...path]/route.ts").read_text(encoding="utf-8")
    proxy_runtime = (ROOT / "apps/admin-portal/lib/server/api-proxy.ts").read_text(encoding="utf-8")
    runtime_match = re.search(
        r"^FROM\s+\S+\s+AS\s+runtime\s*$([\s\S]*?)(?=^FROM\s|\Z)",
        dockerfile,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    runtime_section = runtime_match.group(1) if runtime_match else ""

    checks = {
        "required_files_exist": all(path.exists() for path in (DOCKERFILE, NEXT_CONFIG, BAKE)),
        "next_standalone_enabled": "output: 'standalone'" in next_config or 'output: "standalone"' in next_config,
        "dockerfile_has_dependencies_stage": "AS dependencies" in dockerfile,
        "dockerfile_has_build_stage": "AS build" in dockerfile,
        "dockerfile_has_runtime_stage": "AS runtime" in dockerfile,
        "runtime_stage_is_parseable": bool(runtime_match),
        "dockerfile_preserves_optional_external_api_build_arg": "ARG NEXT_PUBLIC_API_BASE_URL" in dockerfile,
        "dockerfile_does_not_embed_localhost_api": "http://localhost:8000" not in dockerfile,
        "next_proxy_uses_runtime_api_origin": "createApiProxy" in proxy_route
        and "API_INTERNAL_BASE_URL" in proxy_runtime,
        "runtime_copies_standalone": "/.next/standalone" in runtime_section,
        "runtime_copies_static_assets": "/.next/static" in runtime_section,
        "runtime_does_not_copy_repository": "COPY . ." not in runtime_section,
        "runtime_does_not_run_npm_install": "npm ci" not in runtime_section and "npm install" not in runtime_section,
        "runtime_uses_non_root_user": "USER platform" in runtime_section,
        "runtime_has_fixed_uid": "--uid 10001" in runtime_section,
        "runtime_has_exec_form_cmd": 'CMD ["node", "apps/admin-portal/server.js"]' in runtime_section,
        "runtime_sets_production_mode": "ENV NODE_ENV=production" in runtime_section,
        "runtime_disables_telemetry": "ENV NEXT_TELEMETRY_DISABLED=1" in runtime_section,
        "bake_keeps_multiarch": '"linux/amd64"' in bake and '"linux/arm64"' in bake,
        "bake_keeps_sbom": '"type=sbom"' in bake,
        "bake_keeps_provenance": '"type=provenance,mode=max"' in bake,
        "bake_does_not_embed_browser_api_origin": "NEXT_PUBLIC_API_BASE_URL" not in bake,
    }

    result = {
        "stage": "portal_production_image_contract",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
