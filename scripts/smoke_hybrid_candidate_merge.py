#!/usr/bin/env python3
"""Smoke validation for Sprint 13.4 hybrid candidate merge."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_merge_metrics(response: dict[str, Any], *, requested_mode: str) -> dict[str, Any]:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("hybrid_merge_contract") == "weighted_hybrid_candidate_merge_v1", "hybrid merge contract mismatch")
    assert_true(metrics.get("hybrid_merge_enabled") is True, "hybrid merge must be enabled")
    assert_true(metrics.get("hybrid_merge_executed") is True, "hybrid merge must execute")
    assert_true(metrics.get("hybrid_merger") == "weighted_hybrid_merger_v1", "hybrid merger mismatch")
    assert_true(metrics.get("hybrid_merge_requested_mode") == requested_mode, "hybrid merge requested mode mismatch")
    assert_true(metrics.get("hybrid_merge_resolved_mode") == "lexical_only", "hybrid merge resolved mode mismatch")
    assert_true(metrics.get("lexical_weight") == 1.0, "lexical weight mismatch")
    assert_true(metrics.get("vector_weight") == 0.0, "vector weight mismatch")
    assert_true(int(metrics.get("lexical_candidate_count") or 0) >= 1, "lexical candidate count missing")
    assert_true(metrics.get("vector_candidate_count") == 0, "vector candidate count must be zero in 13.4")
    assert_true(int(metrics.get("merged_candidate_count") or 0) >= 1, "merged candidate count missing")
    assert_true(metrics.get("hybrid_lexical_only_fallback") is True, "hybrid lexical-only fallback must be true")
    assert_true(metrics.get("hybrid_vector_contribution_count") == 0, "vector contribution count must be zero")
    assert_true(int(metrics.get("hybrid_lexical_contribution_count") or 0) >= 1, "lexical contribution count missing")
    assert_true(metrics.get("hybrid_vector_contribution_available") is False, "vector contribution must not be available in 13.4")
    assert_true(
        metrics.get("hybrid_merge_strategy") == "lexical_weight_1_vector_weight_0_until_vector_provider_available",
        "hybrid merge strategy mismatch",
    )
    return metrics


def _assert_candidate_trace(response: dict[str, Any], collection_key: str) -> None:
    items = response.get(collection_key) or []
    assert_true(len(items) >= 1, f"{collection_key} returned no items")
    trace = ((items[0].get("metadata") or {}).get("hybrid_merge") or {})
    assert_true(trace.get("merger") == "weighted_hybrid_merger_v1", "candidate merge trace missing")
    assert_true(trace.get("lexical_score") is not None, "candidate lexical score missing")
    assert_true(trace.get("vector_score") is None, "candidate vector score must be null in 13.4")
    assert_true(trace.get("merged_score") is not None, "candidate merged score missing")
    assert_true(trace.get("vector_candidate_present") is False, "candidate vector presence must be false")
    assert_true(trace.get("lexical_weight") == 1.0, "candidate lexical weight mismatch")
    assert_true(trace.get("vector_weight") == 0.0, "candidate vector weight mismatch")


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)

    hybrid_search = request(
        "POST",
        base_url,
        "/api/knowledge/search",
        {
            "organization_id": organization_id,
            "query_text": query_text,
            "top_k": 5,
            "candidate_k": 10,
            "retrieval_mode": "hybrid",
            "embedding_enabled": True,
            "embedding_model_ref": "generic-embedding-model-reference-only",
            "embedding_provider_ref": "generic-embedding-provider-reference-only",
            "embedding_dimension": 768,
            "vector_provider_ref": "generic-vector-provider-reference-only",
        },
    )
    hybrid_metrics = _assert_merge_metrics(hybrid_search, requested_mode="hybrid")
    _assert_candidate_trace(hybrid_search, "candidates")
    assert_true(hybrid_metrics.get("resolved_retrieval_mode") == "lexical_only", "hybrid must resolve to lexical_only in 13.4")
    assert_true(hybrid_metrics.get("retrieval_mode_fallback_reason") == "vector_provider_not_configured", "hybrid fallback reason mismatch")

    vector_context = request(
        "POST",
        base_url,
        "/api/knowledge/context",
        {
            "organization_id": organization_id,
            "query_text": query_text,
            "top_k": 5,
            "candidate_k": 10,
            "retrieval_mode": "vector_only",
            "embedding_enabled": True,
            "embedding_model_ref": "generic-embedding-model-reference-only",
            "embedding_provider_ref": "generic-embedding-provider-reference-only",
            "embedding_dimension": 768,
            "vector_provider_ref": "generic-vector-provider-reference-only",
        },
    )
    vector_metrics = _assert_merge_metrics(vector_context, requested_mode="vector_only")
    _assert_candidate_trace(vector_context, "context")
    assert_true(len(vector_context.get("citations") or []) >= 1, "context citations missing")
    assert_true(vector_metrics.get("resolved_retrieval_mode") == "lexical_only", "vector_only must resolve to lexical_only in 13.4")

    lexical_search = request(
        "POST",
        base_url,
        "/api/knowledge/search",
        {
            "organization_id": organization_id,
            "query_text": query_text,
            "top_k": 5,
            "candidate_k": 10,
            "retrieval_mode": "lexical_only",
            "embedding_enabled": False,
        },
    )
    lexical_metrics = _assert_merge_metrics(lexical_search, requested_mode="lexical_only")
    _assert_candidate_trace(lexical_search, "candidates")
    assert_true(lexical_metrics.get("retrieval_mode_fallback_used") is False, "lexical_only must not use retrieval fallback")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "hybrid_requested_mode": hybrid_metrics.get("requested_retrieval_mode"),
        "hybrid_resolved_mode": hybrid_metrics.get("resolved_retrieval_mode"),
        "hybrid_merge_contract": hybrid_metrics.get("hybrid_merge_contract"),
        "hybrid_merger": hybrid_metrics.get("hybrid_merger"),
        "lexical_candidate_count": hybrid_metrics.get("lexical_candidate_count"),
        "vector_candidate_count": hybrid_metrics.get("vector_candidate_count"),
        "merged_candidate_count": hybrid_metrics.get("merged_candidate_count"),
        "hybrid_vector_contribution_count": hybrid_metrics.get("hybrid_vector_contribution_count"),
        "hybrid_lexical_contribution_count": hybrid_metrics.get("hybrid_lexical_contribution_count"),
        "hybrid_lexical_only_fallback": hybrid_metrics.get("hybrid_lexical_only_fallback"),
        "vector_weight": hybrid_metrics.get("vector_weight"),
        "lexical_weight": hybrid_metrics.get("lexical_weight"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 13.4 hybrid candidate merge smoke validation.")
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
