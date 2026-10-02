#!/usr/bin/env python3
"""Sprint 15 runtime registry and resolver smoke validation."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
if str(API_APP) not in sys.path:
    sys.path.insert(0, str(API_APP))

from app.services.runtime_resolver import RuntimeResolverService  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


class EmptyScalarResult:
    def first(self) -> None:
        return None


class EmptySession:
    """Minimal session double for deterministic no-registry resolver cases."""

    def scalars(self, statement: Any) -> EmptyScalarResult:
        del statement
        return EmptyScalarResult()

    def get(self, model: Any, item_id: Any) -> None:
        del model, item_id
        return None


def request_json(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status == 204:
                return None
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SmokeFailure(f"{method} {path} failed: {exc}") from exc


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke(base_url: str) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:10]
    provider_id: str | None = None
    profile_id: str | None = None

    try:
        providers_before = request_json(base_url, "GET", "/api/ai/providers")
        profiles_before = request_json(base_url, "GET", "/api/ai/runtime-profiles")
        assert_true(isinstance(providers_before, list), "Provider list endpoint must return a list")
        assert_true(isinstance(profiles_before, list), "Runtime profile list endpoint must return a list")

        provider = request_json(
            base_url,
            "POST",
            "/api/ai/providers",
            {
                "organization_id": None,
                "provider_key": f"smoke-provider-{suffix}",
                "display_name": "Smoke Provider",
                "adapter_type": "deterministic-smoke",
                "provider_type": "inference",
                "status": "draft",
                "enabled": False,
                "configuration": {},
                "capabilities": {},
                "health_state": "unknown",
                "metadata_json": {"smoke": True},
            },
        )
        provider_id = provider["id"]
        assert_true(provider["enabled"] is False, "Smoke provider must remain disabled")
        assert_true(provider["status"] == "draft", "Smoke provider must be created as draft")

        profile = request_json(
            base_url,
            "POST",
            "/api/ai/runtime-profiles",
            {
                "organization_id": None,
                "profile_key": f"smoke-profile-{suffix}",
                "display_name": "Smoke Runtime Profile",
                "answer_mode": "assisted",
                "provider_id": provider_id,
                "model_id": None,
                "prompt_id": None,
                "guardrail_id": None,
                "generation_enabled": False,
                "fallback_mode": "extractive",
                "configuration": {},
                "status": "draft",
                "is_default": False,
                "metadata_json": {"smoke": True},
            },
        )
        profile_id = profile["id"]
        assert_true(profile["generation_enabled"] is False, "Smoke runtime profile must keep generation disabled")
        assert_true(profile["model_id"] is None, "Runtime profile model reference must remain nullable")
        assert_true(profile["prompt_id"] is None, "Runtime profile prompt reference must remain nullable")
        assert_true(profile["guardrail_id"] is None, "Runtime profile guardrail reference must remain nullable")

        fetched_provider = request_json(base_url, "GET", f"/api/ai/providers/{provider_id}")
        fetched_profile = request_json(base_url, "GET", f"/api/ai/runtime-profiles/{profile_id}")
        assert_true(fetched_provider["provider_key"] == provider["provider_key"], "Provider round trip failed")
        assert_true(fetched_profile["profile_key"] == profile["profile_key"], "Runtime profile round trip failed")

        resolver = RuntimeResolverService()
        empty_session = EmptySession()
        context_only = resolver.resolve(empty_session, organization_id=None, requested_answer_mode="context_only")
        extractive = resolver.resolve(empty_session, organization_id=None, requested_answer_mode="extractive")
        assisted = resolver.resolve(empty_session, organization_id=None, requested_answer_mode="assisted")
        unsupported = resolver.resolve(empty_session, organization_id=None, requested_answer_mode="unsupported-mode")

        assert_true(context_only.resolved_answer_mode == "context_only", "context_only resolution failed")
        assert_true(context_only.generation_allowed is False, "context_only must not allow generation")
        assert_true(extractive.resolved_answer_mode == "extractive", "extractive resolution failed")
        assert_true(extractive.fallback_used is False, "extractive must not be represented as fallback")
        assert_true(assisted.resolved_answer_mode == "extractive", "assisted without profile must fall back")
        assert_true(assisted.fallback_reason == "runtime_profile_not_configured", "assisted fallback reason mismatch")
        assert_true(unsupported.fallback_reason == "unsupported_answer_mode", "unsupported mode fallback reason mismatch")

        return {
            "status": "passed",
            "sprint": "15.6",
            "validation": "sprint_15_runtime_registry",
            "cases": {
                "provider_registry_crud": "passed",
                "runtime_profile_registry_crud": "passed",
                "nullable_runtime_references": "passed",
                "context_only_resolution": "passed",
                "extractive_resolution": "passed",
                "assisted_no_registry_fallback": "passed",
                "unsupported_mode_fallback": "passed",
            },
            "registry": {
                "providers_before": len(providers_before),
                "runtime_profiles_before": len(profiles_before),
                "provider_created_disabled": True,
                "runtime_profile_created_draft": True,
                "generation_enabled": False,
            },
            "resolver": {
                "context_only": context_only.resolved_answer_mode,
                "extractive": extractive.resolved_answer_mode,
                "assisted_without_profile": assisted.resolved_answer_mode,
                "assisted_fallback_reason": assisted.fallback_reason,
                "unsupported_fallback_reason": unsupported.fallback_reason,
                "provider_execution_performed": False,
                "generation_performed": False,
            },
        }
    finally:
        if profile_id is not None:
            try:
                request_json(base_url, "DELETE", f"/api/ai/runtime-profiles/{profile_id}")
            except SmokeFailure:
                pass
        if provider_id is not None:
            try:
                request_json(base_url, "DELETE", f"/api/ai/providers/{provider_id}")
            except SmokeFailure:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 15 runtime registry smoke validation.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    try:
        result = run_smoke(args.base_url)
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
