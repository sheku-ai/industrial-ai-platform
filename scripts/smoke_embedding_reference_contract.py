#!/usr/bin/env python3
"""Smoke validation for Sprint 13.1 embedding model reference contract."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_contract(response: dict[str, Any], *, requested_mode: str, resolved_mode: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("retrieval_contract_version") == "retrieval_mode_contract_v1", "retrieval contract version mismatch")
    assert_true(metrics.get("requested_retrieval_mode") == requested_mode, "requested retrieval mode mismatch")
    assert_true(metrics.get("resolved_retrieval_mode") == resolved_mode, "resolved retrieval mode mismatch")
    assert_true(metrics.get("retrieval_mode") == resolved_mode, "retrieval mode metric mismatch")
    assert_true(metrics.get("lexical_retrieval_enabled") is True, "lexical retrieval must remain enabled")
    assert_true(metrics.get("lexical_retrieval_provider") == "postgres_fts", "lexical provider mismatch")
    assert_true(metrics.get("vector_retrieval_enabled") is False, "vector retrieval must not execute in 13.1")
    assert_true(metrics.get("vector_provider_configured") is False, "vector provider must not be configured in 13.1")
    assert_true(metrics.get("embedding_execution_enabled") is False, "embedding execution must be disabled in 13.1")


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)

    lexical = request(
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
    _assert_contract(lexical, requested_mode="lexical_only", resolved_mode="lexical_only")
    assert_true((lexical.get("metrics") or {}).get("retrieval_mode_fallback_used") is False, "lexical mode must not fallback")

    hybrid = request(
        "POST",
        base_url,
        "/api/knowledge/context",
        {
            "organization_id": organization_id,
            "query_text": query_text,
            "top_k": 5,
            "candidate_k": 10,
            "retrieval_mode": "hybrid",
            "embedding_enabled": True,
            "embedding_model_ref": "bge-m3-reference-only",
            "embedding_provider_ref": "local-embedding-provider-reference-only",
            "embedding_dimension": 1024,
            "vector_provider_ref": "qdrant-reference-only",
        },
    )
    _assert_contract(hybrid, requested_mode="hybrid", resolved_mode="lexical_only")
    hybrid_metrics = hybrid.get("metrics") or {}
    assert_true(hybrid_metrics.get("retrieval_mode_fallback_used") is True, "hybrid request should fallback in 13.1")
    assert_true(hybrid_metrics.get("retrieval_mode_fallback_reason") == "vector_provider_not_configured", "hybrid fallback reason mismatch")
    assert_true(hybrid_metrics.get("embedding_enabled") is True, "embedding enabled flag was not preserved")
    assert_true(hybrid_metrics.get("embedding_requested") is True, "embedding requested flag missing")
    assert_true(hybrid_metrics.get("embedding_model_ref") == "bge-m3-reference-only", "embedding model ref was not preserved")
    assert_true(hybrid_metrics.get("embedding_provider_ref") == "local-embedding-provider-reference-only", "embedding provider ref was not preserved")
    assert_true(hybrid_metrics.get("embedding_dimension") == 1024, "embedding dimension was not preserved")
    assert_true(hybrid_metrics.get("vector_provider_ref") == "qdrant-reference-only", "vector provider ref was not preserved")
    assert_true(hybrid_metrics.get("embedding_status") == "configured_not_executed", "embedding status mismatch")
    assert_true(hybrid_metrics.get("embedding_fallback_reason") == "embedding_execution_not_configured", "embedding fallback reason mismatch")
    assert_true(len(hybrid.get("context") or []) >= 1, "hybrid fallback context should still return evidence")
    assert_true(len(hybrid.get("citations") or []) >= 1, "hybrid fallback should still return citations")

    vector_only = request(
        "POST",
        base_url,
        "/api/knowledge/search",
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
    _assert_contract(vector_only, requested_mode="vector_only", resolved_mode="lexical_only")
    vector_metrics = vector_only.get("metrics") or {}
    assert_true(vector_metrics.get("retrieval_mode_fallback_used") is True, "vector_only request should fallback in 13.1")
    assert_true(vector_metrics.get("retrieval_mode_fallback_reason") == "vector_provider_not_configured", "vector fallback reason mismatch")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "lexical_requested_mode": (lexical.get("metrics") or {}).get("requested_retrieval_mode"),
        "lexical_resolved_mode": (lexical.get("metrics") or {}).get("resolved_retrieval_mode"),
        "hybrid_requested_mode": hybrid_metrics.get("requested_retrieval_mode"),
        "hybrid_resolved_mode": hybrid_metrics.get("resolved_retrieval_mode"),
        "hybrid_fallback_reason": hybrid_metrics.get("retrieval_mode_fallback_reason"),
        "embedding_enabled": hybrid_metrics.get("embedding_enabled"),
        "embedding_model_ref": hybrid_metrics.get("embedding_model_ref"),
        "embedding_status": hybrid_metrics.get("embedding_status"),
        "vector_only_resolved_mode": vector_metrics.get("resolved_retrieval_mode"),
        "vector_retrieval_enabled": vector_metrics.get("vector_retrieval_enabled"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 13.1 embedding reference contract smoke validation.")
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
