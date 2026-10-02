#!/usr/bin/env python3
"""Smoke validation for Sprint 12.5 fallback and error semantics."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_fallback(answer: dict[str, Any], *, reason: str) -> None:
    metrics = answer.get("metrics") or {}
    assert_true(answer.get("requested_answer_mode") == "assisted", f"requested mode mismatch for {reason}")
    assert_true(answer.get("resolved_answer_mode") == "extractive", f"resolved mode mismatch for {reason}")
    assert_true(answer.get("fallback_used") is True, f"fallback flag missing for {reason}")
    assert_true(answer.get("fallback_reason") == reason, f"fallback reason mismatch for {reason}")
    assert_true(answer.get("answer_generated") is False, f"answer must not be generated for {reason}")
    assert_true(answer.get("llm_used") is False, f"llm_used must be false for {reason}")
    assert_true(metrics.get("answer_mode") == "extractive", f"metrics answer_mode mismatch for {reason}")
    assert_true(metrics.get("fallback_reason") == reason, f"metrics fallback reason mismatch for {reason}")
    assert_true(metrics.get("answer_generated") is False, f"metrics answer_generated mismatch for {reason}")
    assert_true(metrics.get("llm_used") is False, f"metrics llm_used mismatch for {reason}")


def _request_answer(base_url: str, organization_id: str, query_text: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "organization_id": organization_id,
        "query_text": query_text,
        "top_k": 5,
        "candidate_k": 10,
        "facet_fields": ["content_type", "metadata.validation"],
        "answer_mode": "assisted",
        "provider_ref": "deterministic-grounded",
        "model_ref": "deterministic-grounded-model",
        "prompt_ref": "default-grounded-answer",
        "guardrail_ref": "default-grounding-policy",
    }
    payload.update(overrides)
    return request("POST", base_url, "/api/knowledge/answer", payload)


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)

    provider_failure = _request_answer(
        base_url,
        organization_id,
        query_text,
        provider_ref="deterministic-failure",
    )
    _assert_fallback(provider_failure, reason="provider_failed")
    assert_true((provider_failure.get("metrics") or {}).get("inference_provider_adapter") == "deterministic_failure_provider_v1", "provider failure adapter mismatch")

    provider_timeout = _request_answer(
        base_url,
        organization_id,
        query_text,
        provider_ref="deterministic-timeout",
    )
    _assert_fallback(provider_timeout, reason="provider_timeout")
    assert_true((provider_timeout.get("metrics") or {}).get("inference_provider_adapter") == "deterministic_timeout_provider_v1", "provider timeout adapter mismatch")

    prompt_unresolved = _request_answer(
        base_url,
        organization_id,
        query_text,
        prompt_ref="unresolved-prompt",
    )
    _assert_fallback(prompt_unresolved, reason="prompt_ref_unresolved")
    assert_true((prompt_unresolved.get("metrics") or {}).get("prompt_resolved") is False, "prompt should be unresolved")
    assert_true((prompt_unresolved.get("metrics") or {}).get("inference_provider_adapter") is None, "provider should not be called when prompt is unresolved")

    guardrail_blocked = _request_answer(
        base_url,
        organization_id,
        query_text,
        guardrail_ref="blocked-grounding-policy",
    )
    _assert_fallback(guardrail_blocked, reason="guardrail_blocked")
    assert_true((guardrail_blocked.get("metrics") or {}).get("guardrail_allowed") is False, "guardrail should block")
    assert_true((guardrail_blocked.get("metrics") or {}).get("inference_provider_adapter") is None, "provider should not be called when guardrail blocks")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "provider_failed": provider_failure.get("fallback_reason"),
        "provider_timeout": provider_timeout.get("fallback_reason"),
        "prompt_ref_unresolved": prompt_unresolved.get("fallback_reason"),
        "guardrail_blocked": guardrail_blocked.get("fallback_reason"),
        "answer_generated": False,
        "llm_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 12.5 fallback and error semantics smoke validation.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--query", default="PostgreSQL source of truth")
    args = parser.parse_args()

    try:
        result = run_smoke(args.base_url, args.query)
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
