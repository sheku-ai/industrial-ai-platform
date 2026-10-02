#!/usr/bin/env python3
"""Consolidated Sprint 13 runtime smoke validation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from smoke_derived_vector_index_lifecycle import run_smoke as run_derived_vector_index_lifecycle
from smoke_embedding_reference_contract import run_smoke as run_embedding_reference_contract
from smoke_hybrid_candidate_merge import run_smoke as run_hybrid_candidate_merge
from smoke_knowledge_runtime import SmokeFailure
from smoke_retrieval_contribution_metrics import run_smoke as run_retrieval_contribution_metrics
from smoke_vector_provider_abstraction import run_smoke as run_vector_provider_abstraction

SmokeFn = Callable[[str, str], dict[str, Any]]


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    cases: tuple[tuple[str, SmokeFn], ...] = (
        ("embedding_reference_contract", run_embedding_reference_contract),
        ("vector_provider_abstraction", run_vector_provider_abstraction),
        ("derived_vector_index_lifecycle", run_derived_vector_index_lifecycle),
        ("hybrid_candidate_merge", run_hybrid_candidate_merge),
        ("retrieval_contribution_metrics", run_retrieval_contribution_metrics),
    )

    results: dict[str, dict[str, Any]] = {}
    case_status: dict[str, str] = {}
    for name, fn in cases:
        result = fn(base_url, query_text)
        if result.get("status") != "passed":
            raise SmokeFailure(f"Sprint 13 case failed: {name}")
        results[name] = result
        case_status[name] = "passed"

    embedding = results["embedding_reference_contract"]
    vector_provider = results["vector_provider_abstraction"]
    vector_index = results["derived_vector_index_lifecycle"]
    hybrid_merge = results["hybrid_candidate_merge"]
    contribution = results["retrieval_contribution_metrics"]

    return {
        "status": "passed",
        "sprint": "13.6",
        "validation": "sprint_13_runtime_consolidated",
        "case_count": len(cases),
        "cases": case_status,
        "retrieval_modes": {
            "lexical_requested": embedding.get("lexical_requested_mode"),
            "lexical_resolved": embedding.get("lexical_resolved_mode"),
            "hybrid_requested": embedding.get("hybrid_requested_mode"),
            "hybrid_resolved": embedding.get("hybrid_resolved_mode"),
            "vector_only_resolved": embedding.get("vector_only_resolved_mode"),
            "fallback_reason": embedding.get("hybrid_fallback_reason"),
        },
        "embedding_contract": {
            "embedding_enabled": embedding.get("embedding_enabled"),
            "embedding_model_ref": embedding.get("embedding_model_ref"),
            "embedding_status": embedding.get("embedding_status"),
        },
        "vector_provider": {
            "adapter": vector_provider.get("vector_provider_adapter"),
            "status": vector_provider.get("vector_provider_status"),
            "error_code": vector_provider.get("vector_provider_error_code"),
            "vector_retrieval_enabled": vector_provider.get("vector_retrieval_enabled"),
        },
        "vector_index_lifecycle": {
            "index_target": vector_index.get("index_target"),
            "index_status": vector_index.get("index_status"),
            "vector_index_status": vector_index.get("vector_index_status"),
            "vector_index_derived": vector_index.get("vector_index_derived"),
            "vector_index_rebuildable": vector_index.get("vector_index_rebuildable"),
            "vector_index_persisted": vector_index.get("vector_index_persisted"),
            "vector_index_write_enabled": vector_index.get("vector_index_write_enabled"),
            "embedding_generated": vector_index.get("embedding_generated"),
            "vector_indexed": vector_index.get("vector_indexed"),
        },
        "hybrid_merge": {
            "contract": hybrid_merge.get("hybrid_merge_contract"),
            "merger": hybrid_merge.get("hybrid_merger"),
            "lexical_candidate_count": hybrid_merge.get("lexical_candidate_count"),
            "vector_candidate_count": hybrid_merge.get("vector_candidate_count"),
            "merged_candidate_count": hybrid_merge.get("merged_candidate_count"),
            "lexical_weight": hybrid_merge.get("lexical_weight"),
            "vector_weight": hybrid_merge.get("vector_weight"),
            "vector_contribution_count": hybrid_merge.get("hybrid_vector_contribution_count"),
        },
        "retrieval_contribution": {
            "contract": contribution.get("retrieval_contribution_contract"),
            "status": contribution.get("retrieval_contribution_status"),
            "source_of_truth": contribution.get("retrieval_contribution_source_of_truth"),
            "lexical_share": contribution.get("retrieval_contribution_lexical_share"),
            "vector_share": contribution.get("retrieval_contribution_vector_share"),
            "fallback_reason": contribution.get("retrieval_contribution_fallback_reason"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run consolidated Sprint 13 runtime smoke validation.")
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
