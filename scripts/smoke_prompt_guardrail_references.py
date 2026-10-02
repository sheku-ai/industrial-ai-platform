#!/usr/bin/env python3
"""Smoke validation for Sprint 12.3 prompt and guardrail references.

This validates that assisted answer requests resolve prompt and guardrail references
before the disabled provider fallback path. It does not require real generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)
    payload = {
        "organization_id": organization_id,
        "query_text": query_text,
        "top_k": 5,
        "candidate_k": 10,
        "facet_fields": ["content_type", "metadata.validation"],
        "answer_mode": "assisted",
        "provider_ref": "local-default",
        "model_ref": "configured-model",
        "prompt_ref": "default-grounded-answer",
        "guardrail_ref": "default-grounding-policy",
    }
    answer = request("POST", base_url, "/api/knowledge/answer", payload)
    metrics = answer.get("metrics") or {}

    assert_true(answer.get("requested_answer_mode") == "assisted", "assisted request mode not preserved")
    assert_true(answer.get("resolved_answer_mode") == "extractive", "assisted must fall back to extractive")
    assert_true(answer.get("fallback_reason") == "provider_not_configured", "unexpected fallback reason")
    assert_true(metrics.get("prompt_resolved") is True, "prompt reference was not resolved")
    assert_true(metrics.get("prompt_resolver") == "reference_only_prompt_resolver_v1", "unexpected prompt resolver")
    assert_true(metrics.get("prompt_template_ref") == "default-grounded-answer", "prompt template ref mismatch")
    assert_true(metrics.get("guardrail_resolved") is True, "guardrail reference was not resolved")
    assert_true(metrics.get("guardrail_allowed") is True, "guardrail reference should be allowed in 12.3")
    assert_true(metrics.get("guardrail_resolver") == "reference_only_guardrail_resolver_v1", "unexpected guardrail resolver")
    assert_true(metrics.get("guardrail_policy_ref") == "default-grounding-policy", "guardrail policy ref mismatch")
    assert_true(metrics.get("inference_provider_adapter") == "disabled_provider_v1", "disabled provider adapter missing")
    assert_true(metrics.get("inference_success") is False, "disabled provider must not succeed")
    assert_true(answer.get("answer_generated") is False, "12.3 must not generate answers")
    assert_true(answer.get("llm_used") is False, "12.3 must not use LLM")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "requested_answer_mode": answer.get("requested_answer_mode"),
        "resolved_answer_mode": answer.get("resolved_answer_mode"),
        "fallback_reason": answer.get("fallback_reason"),
        "prompt_resolved": metrics.get("prompt_resolved"),
        "prompt_resolver": metrics.get("prompt_resolver"),
        "prompt_template_ref": metrics.get("prompt_template_ref"),
        "guardrail_resolved": metrics.get("guardrail_resolved"),
        "guardrail_allowed": metrics.get("guardrail_allowed"),
        "guardrail_resolver": metrics.get("guardrail_resolver"),
        "guardrail_policy_ref": metrics.get("guardrail_policy_ref"),
        "answer_generated": answer.get("answer_generated"),
        "llm_used": answer.get("llm_used"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 12.3 prompt and guardrail reference smoke validation.")
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
