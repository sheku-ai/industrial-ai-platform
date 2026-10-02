#!/usr/bin/env python3
"""Smoke validation for Sprint 12.1 answer mode contract.

This script assumes the baseline Knowledge Runtime smoke has already inserted generic
validation chunks. It validates answer mode resolution without requiring LLM,
embeddings, BGE, Qdrant, or any external inference provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_answer_contract(response: dict[str, Any], *, requested: str, resolved: str, fallback: bool) -> None:
    metrics = response.get("metrics") or {}
    assert_true(response.get("requested_answer_mode") == requested, f"unexpected requested mode for {requested}")
    assert_true(response.get("resolved_answer_mode") == resolved, f"unexpected resolved mode for {requested}")
    assert_true(response.get("fallback_used") is fallback, f"unexpected fallback flag for {requested}")
    assert_true(response.get("answer_generated") is False, "answer must not be generated in 12.1 smoke")
    assert_true(response.get("llm_used") is False, "LLM must not be used in 12.1 smoke")
    assert_true(metrics.get("answer_contract_version") == "answer_mode_contract_v1", "answer contract version missing")
    assert_true(metrics.get("requested_answer_mode") == requested, f"metrics requested mode mismatch for {requested}")
    assert_true(metrics.get("resolved_answer_mode") == resolved, f"metrics resolved mode mismatch for {requested}")
    assert_true(metrics.get("answer_mode") == resolved, f"metrics answer mode mismatch for {requested}")
    assert_true(metrics.get("answer_generated") is False, "metrics answer_generated must be false")
    assert_true(metrics.get("llm_used") is False, "metrics llm_used must be false")
    assert_true(metrics.get("fallback_used") is fallback, f"metrics fallback flag mismatch for {requested}")


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)
    common_payload = {
        "organization_id": organization_id,
        "query_text": query_text,
        "top_k": 5,
        "candidate_k": 10,
        "facet_fields": ["content_type", "metadata.validation"],
    }

    context_only = request("POST", base_url, "/api/knowledge/answer", {**common_payload, "answer_mode": "context_only"})
    _assert_answer_contract(context_only, requested="context_only", resolved="context_only", fallback=False)
    assert_true(context_only.get("answer") is None, "context_only must not construct an answer")
    assert_true(len(context_only.get("context") or []) >= 1, "context_only returned no context")
    assert_true(len(context_only.get("citations") or []) >= 1, "context_only returned no citations")

    extractive = request("POST", base_url, "/api/knowledge/answer", {**common_payload, "answer_mode": "extractive"})
    _assert_answer_contract(extractive, requested="extractive", resolved="extractive", fallback=False)
    assert_true(extractive.get("answer") is not None, "extractive must construct an answer")

    assisted = request(
        "POST",
        base_url,
        "/api/knowledge/answer",
        {
            **common_payload,
            "answer_mode": "assisted",
            "provider_ref": "local-default",
            "model_ref": "configured-model",
            "prompt_ref": "default-grounded-answer",
            "guardrail_ref": "default-grounding-policy",
        },
    )
    _assert_answer_contract(assisted, requested="assisted", resolved="extractive", fallback=True)
    assert_true(assisted.get("fallback_reason") == "provider_not_configured", "unexpected assisted fallback reason")
    assert_true((assisted.get("metrics") or {}).get("fallback_reason") == "provider_not_configured", "metrics fallback reason missing")
    assert_true(assisted.get("provider_ref") == "local-default", "provider_ref was not echoed")
    assert_true(assisted.get("model_ref") == "configured-model", "model_ref was not echoed")
    assert_true(assisted.get("prompt_ref") == "default-grounded-answer", "prompt_ref was not echoed")
    assert_true(assisted.get("guardrail_ref") == "default-grounding-policy", "guardrail_ref was not echoed")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "context_only_mode": context_only.get("resolved_answer_mode"),
        "extractive_mode": extractive.get("resolved_answer_mode"),
        "assisted_requested_mode": assisted.get("requested_answer_mode"),
        "assisted_resolved_mode": assisted.get("resolved_answer_mode"),
        "assisted_fallback_used": assisted.get("fallback_used"),
        "assisted_fallback_reason": assisted.get("fallback_reason"),
        "answer_generated": assisted.get("answer_generated"),
        "llm_used": assisted.get("llm_used"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 12.1 answer mode contract smoke validation.")
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
