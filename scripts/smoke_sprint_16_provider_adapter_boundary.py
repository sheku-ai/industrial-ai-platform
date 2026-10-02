#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.contracts.runtime_execution import ProviderExecutionRequest  # noqa: E402
from app.providers import (  # noqa: E402
    DisabledProviderAdapter,
    ProviderAdapterRegistry,
)


class SmokeFailure(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke() -> dict[str, object]:
    registry = ProviderAdapterRegistry()
    disabled = registry.resolve(None)
    unknown = registry.resolve("not-registered")

    check(isinstance(disabled, DisabledProviderAdapter), "Default adapter must be disabled")
    check(unknown is disabled, "Unknown adapter must resolve to disabled adapter")
    check(registry.registered_types() == ("disabled",), "Only disabled adapter should be registered by default")

    capabilities = disabled.capabilities()
    health = disabled.health_check()
    request = ProviderExecutionRequest(
        request_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        adapter_type="disabled",
        model_ref="not-configured",
        rendered_prompt="No execution should occur.",
    )
    result = disabled.execute(request)

    check(capabilities.generation is False, "Disabled adapter must not support generation")
    check(health.status == "disabled", "Disabled adapter health must be disabled")
    check(result.status == "failed", "Disabled adapter execution must fail safely")
    check(result.provider_error_code == "provider_not_available", "Unexpected disabled error code")
    check(result.retryable is False, "Disabled adapter result must not be retryable")
    check(result.provider_metadata.get("network_call_performed") is False, "Network call must not occur")
    check(result.provider_metadata.get("generation_performed") is False, "Generation must not occur")

    duplicate_rejected = False
    try:
        registry.register(DisabledProviderAdapter())
    except ValueError:
        duplicate_rejected = True
    check(duplicate_rejected, "Duplicate registration must be rejected")

    return {
        "status": "passed",
        "sprint": "16.2",
        "validation": "provider_adapter_boundary",
        "registered_types": list(registry.registered_types()),
        "unknown_adapter_resolves_disabled": True,
        "duplicate_registration_rejected": True,
        "network_call_performed": False,
        "generation_performed": False,
        "provider_error_code": result.provider_error_code,
    }


def main() -> int:
    try:
        result = run_smoke()
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
