#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "apps/api/Dockerfile"
BAKE = ROOT / "docker-bake.hcl"


def main() -> int:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    bake = BAKE.read_text(encoding="utf-8")
    runtime_match = re.search(
        r"^FROM\s+\S+\s+AS\s+runtime\s*$([\s\S]*?)(?=^FROM\s|\Z)",
        dockerfile,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    runtime_section = runtime_match.group(1) if runtime_match else ""

    checks = {
        "required_files_exist": all(path.exists() for path in (DOCKERFILE, BAKE)),
        "dockerfile_has_dependencies_stage": "AS dependencies" in dockerfile,
        "dockerfile_has_runtime_stage": "AS runtime" in dockerfile,
        "runtime_stage_is_parseable": bool(runtime_match),
        "dependencies_use_virtualenv": "python -m venv" in dockerfile,
        "dependencies_disable_bytecode_compilation": "--no-compile" in dockerfile,
        "runtime_copies_virtualenv": "COPY --from=dependencies /opt/venv /opt/venv" in runtime_section,
        "runtime_does_not_run_pip_install": "pip install" not in runtime_section,
        "runtime_preserves_ocr_packages": "tesseract-ocr" in runtime_section and "tesseract-ocr-eng" in runtime_section,
        "runtime_preserves_fonts": "fonts-dejavu-core" in runtime_section,
        "runtime_uses_non_root_user": "USER platform" in runtime_section,
        "runtime_has_fixed_uid": "--uid 10001" in runtime_section,
        "runtime_has_exec_form_cmd": 'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]'
        in runtime_section,
        "runtime_sets_virtualenv_path": 'PATH="/opt/venv/bin:$PATH"' in runtime_section,
        "runtime_sets_noninteractive_apt": "DEBIAN_FRONTEND=noninteractive" in runtime_section,
        "runtime_cleans_apt_metadata": "rm -rf /var/lib/apt/lists/*" in runtime_section,
        "runtime_uses_copy_chown": "COPY --chown=platform:platform . ." in runtime_section,
        "runtime_avoids_recursive_chown": "chown -R" not in runtime_section,
        "runtime_prepares_writable_runtime_dir": "chown platform:platform /app/runtime" in runtime_section,
        "bake_keeps_multiarch": '"linux/amd64"' in bake and '"linux/arm64"' in bake,
        "bake_keeps_sbom": '"type=sbom"' in bake,
        "bake_keeps_provenance": '"type=provenance,mode=max"' in bake,
    }

    result = {
        "stage": "api_production_image_contract",
        "passed": all(checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
