#!/usr/bin/env python3
"""Smoke validation for Sprint 12.4 assisted answer runtime.

This validates assisted-success semantics through the explicit deterministic
provider. It does not require Ollama, GPU, external AI services, embeddings, or a
vector database.
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
        "provider_ref": "deterministic-grounded",
        "model_ref": "deterministic-grounded-model",
        "prompt_ref": "default-grounded-answer",
        "guardrail_ref": "default-grounding-policy",
    }
    answer = request("POST", base_url, "/api/knowledge/answer", payload)
    metrics = answer.get("metrics") or {}

    assert_true(answer.get("requested_answer_mode") == "assisted", "assisted request mode not preserved")
    assert_true(answer.get("resolved_answer_mode") == "assisted", "assisted provider must resolve to assisted")
    assert_true(answer.get("fallback_used") is False, "assisted success must not use fallback")
    assert_true(answer.get("fallback_reason") is None, "assisted success must not include fallback reason")
    assert_true(answer.get("answer_generated") is True, "assisted success must generate an answer")
    assert_true(answer.get("llm_used") is True, "assisted success must mark llm_used true by contract")
    assert_true(isinstance(answer.get("answer"), str) and answer["answer"].startswith("Assisted answer based only on retrieved evidence"), "assisted answer text missing")
    assert_true(len(answer.get("citations") or []) >= 1, "assisted answer must include citations")
    assert_true(metrics.get("answer_mode") == "assisted", "metrics answer mode mismatch")
    assert_true(metrics.get("inference_provider_adapter") == "deterministic_grounded_provider_v1", "deterministic provider adapter missing")
    assert_true(metrics.get("inference_success") is True, "deterministic provider must succeed")
    assert_true(metrics.get("inference_error_code") is None, "assisted success must not include inference error")
    assert_true(metrics.get("assisted_generation_strategy") == "deterministic_grounded_context_v1", "assisted strategy missing")
    assert_true(metrics.get("prompt_resolved") is True, "prompt reference was not resolved")
    assert_true(metrics.get("guardrail_resolved") is True, "guardrail reference was not resolved")
    assert_true(metrics.get("guardrail_allowed") is True, "guardrail should be allowed")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "requested_answer_mode": answer.get("requested_answer_mode"),
        "resolved_answer_mode": answer.get("resolved_answer_mode"),
        "fallback_used": answer.get("fallback_used"),
        "fallback_reason": answer.get("fallback_reason"),
        "answer_generated": answer.get("answer_generated"),
        "llm_used": answer.get("llm_used"),
        "inference_provider_adapter": metrics.get("inference_provider_adapter"),
        "inference_success": metrics.get("inference_success"),
        "assisted_generation_strategy": metrics.get("assisted_generation_strategy"),
        "citation_count": len(answer.get("citations") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 12.4 assisted answer runtime smoke validation.")
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
