#!/usr/bin/env python3
"""Smoke validation for Sprint 12.2 inference provider abstraction.

This validates that assisted answer requests pass through the provider abstraction
and safely fall back through the disabled provider without requiring an LLM.
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
    assert_true(answer.get("resolved_answer_mode") == "extractive", "assisted must fall back to extractive in 12.2")
    assert_true(answer.get("fallback_used") is True, "assisted fallback flag missing")
    assert_true(answer.get("fallback_reason") == "provider_not_configured", "unexpected fallback reason")
    assert_true(answer.get("answer_generated") is False, "disabled provider must not generate an answer")
    assert_true(answer.get("llm_used") is False, "disabled provider must not use an LLM")
    assert_true(metrics.get("inference_provider_adapter") == "disabled_provider_v1", "provider abstraction adapter missing")
    assert_true(metrics.get("inference_success") is False, "disabled provider must return unsuccessful inference")
    assert_true(metrics.get("inference_error_code") == "provider_not_configured", "provider error code missing")
    assert_true(metrics.get("provider_ref") == "local-default", "provider_ref not preserved")
    assert_true(metrics.get("model_ref") == "configured-model", "model_ref not preserved")
    assert_true(metrics.get("prompt_ref") == "default-grounded-answer", "prompt_ref not preserved")
    assert_true(metrics.get("guardrail_ref") == "default-grounding-policy", "guardrail_ref not preserved")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "requested_answer_mode": answer.get("requested_answer_mode"),
        "resolved_answer_mode": answer.get("resolved_answer_mode"),
        "fallback_used": answer.get("fallback_used"),
        "fallback_reason": answer.get("fallback_reason"),
        "inference_provider_adapter": metrics.get("inference_provider_adapter"),
        "inference_success": metrics.get("inference_success"),
        "inference_error_code": metrics.get("inference_error_code"),
        "answer_generated": answer.get("answer_generated"),
        "llm_used": answer.get("llm_used"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 12.2 inference provider abstraction smoke validation.")
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
