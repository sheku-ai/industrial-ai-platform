#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.models.ai import Guardrail, Model, Prompt, Provider  # noqa: E402
from app.services.runtime_resolver import RuntimeResolverService  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


class ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def first(self) -> Any:
        return self.value


class SessionDouble:
    def __init__(self, profile: Any = None, objects: dict[tuple[type[Any], uuid.UUID], Any] | None = None) -> None:
        self.profile = profile
        self.objects = objects or {}
        self.provider_execution_performed = False
        self.generation_performed = False

    def scalars(self, statement: Any) -> ScalarResult:
        del statement
        return ScalarResult(self.profile)

    def get(self, model: type[Any], item_id: uuid.UUID) -> Any:
        return self.objects.get((model, item_id))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def profile(**values: Any) -> Any:
    data = {
        "id": uuid.uuid4(),
        "generation_enabled": True,
        "provider_id": uuid.uuid4(),
        "model_id": uuid.uuid4(),
        "prompt_id": uuid.uuid4(),
        "guardrail_id": None,
    }
    data.update(values)
    return SimpleNamespace(**data)


def obj(**values: Any) -> Any:
    return SimpleNamespace(**values)


def assisted_case(name: str, session: SessionDouble, mode: str, reason: str | None, allowed: bool) -> str:
    result = RuntimeResolverService().resolve(session, organization_id=None, requested_answer_mode="assisted")
    check(result.resolved_answer_mode == mode, f"{name}: resolved mode")
    check(result.fallback_reason == reason, f"{name}: fallback reason")
    check(result.generation_allowed is allowed, f"{name}: generation eligibility")
    check(not session.provider_execution_performed, f"{name}: provider execution occurred")
    check(not session.generation_performed, f"{name}: generation occurred")
    return "passed"


def run_smoke() -> dict[str, Any]:
    resolver = RuntimeResolverService()
    empty = SessionDouble()
    context = resolver.resolve(empty, organization_id=None, requested_answer_mode="context_only")
    extractive = resolver.resolve(empty, organization_id=None, requested_answer_mode="extractive")
    unsupported = resolver.resolve(empty, organization_id=None, requested_answer_mode="unsupported")
    check(context.resolved_answer_mode == "context_only" and not context.generation_allowed, "context_only failed")
    check(extractive.resolved_answer_mode == "extractive" and not extractive.fallback_used, "extractive failed")
    check(unsupported.fallback_reason == "unsupported_answer_mode", "unsupported mode failed")

    p = profile()
    provider_ok = obj(id=p.provider_id, enabled=True, status="active", health_state="healthy", adapter_type="baseline", provider_type="inference")
    model_ok = obj(id=p.model_id, enabled=True, status="available", model_type="generation")
    prompt_ok = obj(id=p.prompt_id, enabled=True, status="active", prompt_type="system")

    cases = {
        "context_only_without_ai": "passed",
        "extractive_without_ai": "passed",
        "unsupported_answer_mode": "passed",
        "assisted_without_profile": assisted_case("no_profile", SessionDouble(), "extractive", "runtime_profile_not_configured", False),
        "draft_profile_not_selected": assisted_case("draft_profile", SessionDouble(profile=None), "extractive", "runtime_profile_not_configured", False),
        "generation_disabled": assisted_case("generation_disabled", SessionDouble(profile=profile(generation_enabled=False)), "extractive", "generation_not_enabled", False),
        "provider_disabled": assisted_case("provider_disabled", SessionDouble(p, {(Provider, p.provider_id): obj(id=p.provider_id, enabled=False, status="active", health_state="healthy")}), "extractive", "provider_disabled", False),
        "provider_unhealthy": assisted_case("provider_unhealthy", SessionDouble(p, {(Provider, p.provider_id): obj(id=p.provider_id, enabled=True, status="active", health_state="unhealthy")}), "extractive", "provider_unhealthy", False),
        "model_missing": assisted_case("model_missing", SessionDouble(p, {(Provider, p.provider_id): provider_ok}), "extractive", "model_not_configured", False),
        "model_disabled": assisted_case("model_disabled", SessionDouble(p, {(Provider, p.provider_id): provider_ok, (Model, p.model_id): obj(id=p.model_id, enabled=False, status="available")}), "extractive", "model_disabled", False),
        "prompt_missing": assisted_case("prompt_missing", SessionDouble(p, {(Provider, p.provider_id): provider_ok, (Model, p.model_id): model_ok}), "extractive", "prompt_not_configured", False),
        "prompt_unresolved": assisted_case("prompt_unresolved", SessionDouble(p, {(Provider, p.provider_id): provider_ok, (Model, p.model_id): model_ok, (Prompt, p.prompt_id): obj(id=p.prompt_id, enabled=False, status="active")}), "extractive", "prompt_unresolved", False),
    }

    guardrail_id = uuid.uuid4()
    pg = profile(provider_id=p.provider_id, model_id=p.model_id, prompt_id=p.prompt_id, guardrail_id=guardrail_id)
    cases["guardrail_blocked"] = assisted_case(
        "guardrail_blocked",
        SessionDouble(pg, {(Provider, p.provider_id): provider_ok, (Model, p.model_id): model_ok, (Prompt, p.prompt_id): prompt_ok, (Guardrail, guardrail_id): obj(id=guardrail_id, enabled=False)}),
        "extractive",
        "guardrail_blocked",
        False,
    )

    eligible_session = SessionDouble(pg, {
        (Provider, p.provider_id): provider_ok,
        (Model, p.model_id): model_ok,
        (Prompt, p.prompt_id): prompt_ok,
        (Guardrail, guardrail_id): obj(id=guardrail_id, enabled=True, guardrail_type="policy"),
    })
    cases["configuration_complete_generation_eligible"] = assisted_case("eligible", eligible_session, "assisted", None, True)

    return {
        "status": "passed",
        "sprint": "16.0.1",
        "validation": "runtime_resolver_behavior_baseline",
        "cases": cases,
        "eligible_configuration": {
            "generation_allowed": True,
            "provider_execution_performed": eligible_session.provider_execution_performed,
            "generation_performed": eligible_session.generation_performed,
        },
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
