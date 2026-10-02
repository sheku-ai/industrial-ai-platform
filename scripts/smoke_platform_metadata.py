#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.platform_metadata import (  # noqa: E402
    CURRENT_SPRINT,
    CURRENT_WORK_PACKAGE,
    PRODUCT_VERSION,
    build_platform_info,
)


def main() -> int:
    settings = Settings()
    info = build_platform_info(settings)

    assert settings.app_version == PRODUCT_VERSION
    assert info.product_version == PRODUCT_VERSION
    assert info.current_sprint == CURRENT_SPRINT
    assert info.current_work_package == CURRENT_WORK_PACKAGE
    assert info.provider_execution_enabled is False
    assert info.feature_flags["ai_provider_execution"] is False
    assert info.no_ai_ready is True

    result = {
        "status": "passed",
        "contract": "PlatformBuildInfo",
        "product_version": info.product_version,
        "current_sprint": info.current_sprint,
        "current_work_package": info.current_work_package,
        "provider_execution_enabled": info.provider_execution_enabled,
        "no_ai_ready": info.no_ai_ready,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
