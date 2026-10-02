#!/usr/bin/env python3
"""Smoke validation for Sprint 13.2 vector provider abstraction."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def _assert_disabled_vector_provider(response: dict[str, Any], *, requested_mode: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("requested_retrieval_mode") == requested_mode, "requested retrieval mode mismatch")
    assert_true(metrics.get("resolved_retrieval_mode") == "lexical_only", "resolved retrieval mode must be lexical_only")
    assert_true(metrics.get("retrieval_mode_fallback_used") is (requested_mode != "lexical_only"), "fallback flag mismatch")
    assert_true(metrics.get("lexical_retrieval_enabled") is True, "lexical retrieval must remain enabled")
    assert_true(metrics.get("lexical_retrieval_provider") == "postgres_fts", "lexical provider mismatch")
    assert_true(metrics.get("vector_retrieval_enabled") is False, "vector retrieval must not execute in 13.2")
    assert_true(metrics.get("vector_provider_adapter") == "disabled_vector_provider_v1", "vector provider adapter mismatch")
    assert_true(metrics.get("vector_provider_configured") is False, "vector provider must be unconfigured")
    assert_true(metrics.get("vector_provider_available") is False, "vector provider must be unavailable")
    assert_true(metrics.get("vector_provider_status") == "disabled", "vector provider status mismatch")
    assert_true(metrics.get("vector_provider_error_code") == "vector_provider_not_configured", "vector provider error mismatch")
    assert_true(metrics.get("vector_provider_resolution") == "disabled_default", "vector provider resolution mismatch")


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    organization_id = get_or_create_organization(base_url)

    hybrid = request(
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
    _assert_disabled_vector_provider(hybrid, requested_mode="hybrid")
    hybrid_metrics = hybrid.get("metrics") or {}
    assert_true(hybrid_metrics.get("retrieval_mode_fallback_reason") == "vector_provider_not_configured", "hybrid fallback reason mismatch")
    assert_true(hybrid_metrics.get("vector_provider_ref") == "generic-vector-provider-reference-only", "vector provider ref was not preserved")

    vector_only = request(
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
            "embedding_model_ref": "another-embedding-model-reference-only",
            "embedding_provider_ref": "another-embedding-provider-reference-only",
            "embedding_dimension": 1024,
            "vector_provider_ref": "another-vector-provider-reference-only",
        },
    )
    _assert_disabled_vector_provider(vector_only, requested_mode="vector_only")
    vector_metrics = vector_only.get("metrics") or {}
    assert_true(len(vector_only.get("context") or []) >= 1, "vector_only fallback should still return context")
    assert_true(len(vector_only.get("citations") or []) >= 1, "vector_only fallback should still return citations")

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
    _assert_disabled_vector_provider(lexical, requested_mode="lexical_only")
    lexical_metrics = lexical.get("metrics") or {}
    assert_true(lexical_metrics.get("retrieval_mode_fallback_used") is False, "lexical_only should not use retrieval fallback")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "hybrid_requested_mode": hybrid_metrics.get("requested_retrieval_mode"),
        "hybrid_resolved_mode": hybrid_metrics.get("resolved_retrieval_mode"),
        "hybrid_fallback_reason": hybrid_metrics.get("retrieval_mode_fallback_reason"),
        "vector_only_resolved_mode": vector_metrics.get("resolved_retrieval_mode"),
        "vector_provider_adapter": hybrid_metrics.get("vector_provider_adapter"),
        "vector_provider_status": hybrid_metrics.get("vector_provider_status"),
        "vector_provider_error_code": hybrid_metrics.get("vector_provider_error_code"),
        "vector_retrieval_enabled": hybrid_metrics.get("vector_retrieval_enabled"),
        "lexical_provider": hybrid_metrics.get("lexical_retrieval_provider"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 13.2 vector provider abstraction smoke validation.")
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
