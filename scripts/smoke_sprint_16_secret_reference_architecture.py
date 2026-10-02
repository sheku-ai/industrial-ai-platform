#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.secret_refs import DisabledSecretResolver, EnvironmentSecretResolver, SecretReference, SecretResolverRegistry  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def check(value: bool, message: str) -> None:
    if not value:
        raise SmokeFailure(message)


def run_smoke() -> dict[str, object]:
    registry = SecretResolverRegistry()
    disabled = registry.resolve(None)
    check(isinstance(disabled, DisabledSecretResolver), "default resolver")
    check(registry.resolve("unknown") is disabled, "unknown resolver fallback")

    disabled_result = disabled.resolve(SecretReference("disabled", "unused"))
    check(disabled_result.status == "disabled", "disabled status")
    check(disabled_result.value is None, "disabled value")

    environment = EnvironmentSecretResolver()
    registry.register(environment)
    missing = environment.resolve(SecretReference("env", "IAP_REFERENCE_SMOKE_MISSING"))
    check(missing.status == "not_found" and missing.value is None, "missing reference")

    name = "IAP_REFERENCE_SMOKE_VALUE"
    value = "temporary-runtime-value"
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        resolved = environment.resolve(SecretReference("env", name))
        check(resolved.status == "resolved" and resolved.value is not None, "environment resolution")
        check(str(resolved.value) == "<redacted>", "redacted string")
        check(value not in repr(resolved), "result exposure")
        check(value not in json.dumps(dict(resolved.metadata)), "metadata exposure")
        check(resolved.value.reveal() == value, "explicit reveal")
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    duplicate_rejected = False
    try:
        registry.register(EnvironmentSecretResolver())
    except ValueError:
        duplicate_rejected = True
    check(duplicate_rejected, "duplicate registration")

    return {
        "status": "passed",
        "sprint": "16.3",
        "validation": "secret_reference_architecture",
        "registered_types": list(registry.registered_types()),
        "unknown_resolver_returns_disabled": True,
        "missing_reference_fails_deterministically": True,
        "value_repr_redacted": True,
        "value_emitted": False,
        "network_call_performed": False,
        "duplicate_registration_rejected": True,
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
