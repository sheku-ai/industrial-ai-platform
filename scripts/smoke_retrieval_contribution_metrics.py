#!/usr/bin/env python3
"""Smoke validation for Sprint 13.5 retrieval contribution metrics."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_contribution_metrics(response: dict[str, Any], collection_key: str) -> dict[str, Any]:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("retrieval_contribution_contract") == "retrieval_contribution_metrics_v1", "contribution contract mismatch")
    assert_true(metrics.get("retrieval_contribution_metrics_enabled") is True, "contribution metrics not enabled")
    assert_true(metrics.get("retrieval_contribution_basis") == "merged_candidates", "contribution basis mismatch")
    assert_true(metrics.get("retrieval_contribution_runtime") == "lexical_only_fallback", "contribution runtime mismatch")
    assert_true(metrics.get("retrieval_contribution_status") == "lexical_only", "contribution status mismatch")
    assert_true(metrics.get("retrieval_contribution_source_of_truth") == "postgres_fts", "source of truth mismatch")
    assert_true(metrics.get("retrieval_contribution_lexical_provider") == "postgres_fts", "lexical provider mismatch")
    assert_true(metrics.get("retrieval_contribution_vector_provider") is None, "vector provider must be null in 13.5")
    assert_true(int(metrics.get("retrieval_contribution_total_candidates") or 0) >= 1, "total contribution candidates missing")
    assert_true(int(metrics.get("retrieval_contribution_lexical_candidates") or 0) >= 1, "lexical candidate contribution missing")
    assert_true(metrics.get("retrieval_contribution_vector_candidates") == 0, "vector candidates must be zero")
    assert_true(int(metrics.get("retrieval_contribution_merged_candidates") or 0) >= 1, "merged contribution candidates missing")
    assert_true(int(metrics.get("retrieval_contribution_lexical_count") or 0) >= 1, "lexical contribution count missing")
    assert_true(metrics.get("retrieval_contribution_vector_count") == 0, "vector contribution count must be zero")
    assert_true(metrics.get("retrieval_contribution_lexical_share") == 1.0, "lexical share must be 1.0")
    assert_true(metrics.get("retrieval_contribution_vector_share") == 0.0, "vector share must be 0.0")
    assert_true(metrics.get("retrieval_contribution_vector_available") is False, "vector contribution must be unavailable")
    assert_true(metrics.get("retrieval_contribution_fallback_active") is True, "contribution fallback must be active")
    assert_true(metrics.get("retrieval_contribution_fallback_reason") == "vector_provider_not_configured", "contribution fallback reason mismatch")

    items = response.get(collection_key) or []
    assert_true(len(items) >= 1, f"{collection_key} returned no items")
    trace = ((items[0].get("metadata") or {}).get("retrieval_contribution") or {})
    assert_true(trace.get("contract") == "retrieval_contribution_metrics_v1", "candidate contribution trace contract missing")
    assert_true(trace.get("lexical_contributed") is True, "candidate lexical contribution missing")
    assert_true(trace.get("vector_contributed") is False, "candidate vector contribution must be false")
    assert_true(trace.get("primary_source") == "lexical", "candidate primary source mismatch")
    assert_true(trace.get("source_of_truth") == "postgres_fts", "candidate source of truth mismatch")
    assert_true(trace.get("vector_available") is False, "candidate vector availability mismatch")
    assert_true(trace.get("fallback_active") is True, "candidate fallback flag mismatch")
    return metrics


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
    hybrid_metrics = _assert_contribution_metrics(hybrid_search, "candidates")

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
    vector_metrics = _assert_contribution_metrics(vector_context, "context")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "retrieval_contribution_contract": hybrid_metrics.get("retrieval_contribution_contract"),
        "retrieval_contribution_status": hybrid_metrics.get("retrieval_contribution_status"),
        "retrieval_contribution_source_of_truth": hybrid_metrics.get("retrieval_contribution_source_of_truth"),
        "retrieval_contribution_lexical_candidates": hybrid_metrics.get("retrieval_contribution_lexical_candidates"),
        "retrieval_contribution_vector_candidates": hybrid_metrics.get("retrieval_contribution_vector_candidates"),
        "retrieval_contribution_lexical_count": hybrid_metrics.get("retrieval_contribution_lexical_count"),
        "retrieval_contribution_vector_count": hybrid_metrics.get("retrieval_contribution_vector_count"),
        "retrieval_contribution_lexical_share": hybrid_metrics.get("retrieval_contribution_lexical_share"),
        "retrieval_contribution_vector_share": hybrid_metrics.get("retrieval_contribution_vector_share"),
        "retrieval_contribution_fallback_reason": hybrid_metrics.get("retrieval_contribution_fallback_reason"),
        "vector_context_contribution_status": vector_metrics.get("retrieval_contribution_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 13.5 retrieval contribution metrics smoke validation.")
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
