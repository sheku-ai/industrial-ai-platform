#!/usr/bin/env python3
"""Smoke validation for Sprint 13.3 derived vector index lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from typing import Any

from smoke_knowledge_runtime import SmokeFailure, assert_true, get_or_create_organization, request


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    run_id = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    organization_id = get_or_create_organization(base_url)

    registration = request(
        "POST",
        base_url,
        "/api/ingestion/register",
        {
            "organization_id": organization_id,
            "title": f"Smoke Derived Vector Index {run_id}",
            "source_type": "controlled_input",
            "source_ref": {"smoke_run_id": run_id},
            "external_reference": f"smoke-derived-vector-index-{run_id}",
            "description": "Automated generic derived vector index lifecycle validation record.",
            "metadata": {"validation": "sprint-13-3", "smoke_run_id": run_id},
            "classification": {},
            "requested_by": "smoke_derived_vector_index_lifecycle",
            "file_name": f"derived-vector-index-{run_id}.txt",
            "content_type": "text/plain",
        },
    )
    document_version_id = registration["document_version_id"]

    chunks = request(
        "POST",
        base_url,
        "/api/documents/chunks/persist",
        {
            "organization_id": organization_id,
            "document_version_id": document_version_id,
            "chunks": [
                {
                    "chunk_index": 0,
                    "text": "Vector indexes are derived and rebuildable from PostgreSQL chunks.",
                    "metadata": {"validation": "sprint-13-3", "smoke_run_id": run_id},
                    "quality": {"smoke": True},
                },
                {
                    "chunk_index": 1,
                    "text": "Lexical retrieval remains the fallback baseline when vector retrieval is unavailable.",
                    "metadata": {"validation": "sprint-13-3", "smoke_run_id": run_id},
                    "quality": {"smoke": True},
                },
            ],
        },
    )
    assert_true(chunks.get("chunk_count") == 2, "expected two chunks for derived vector index smoke")

    job = request(
        "POST",
        base_url,
        "/api/indexing/jobs",
        {
            "organization_id": organization_id,
            "document_version_id": document_version_id,
            "index_target": "vector_derived",
            "vector_provider": "generic-vector-provider-reference-only",
            "vector_collection_name": "generic-derived-vector-index-reference-only",
            "metrics": {"validation": "sprint-13-3", "smoke_run_id": run_id},
        },
    )
    job_metrics = job.get("metrics") or {}
    assert_true(job.get("index_target") == "vector_derived", "index target mismatch")
    assert_true(job.get("status") == "pending", "derived vector job must start pending")
    assert_true(job_metrics.get("indexing_contract") == "derived_vector_index_lifecycle_v1", "indexing contract mismatch")
    assert_true(job_metrics.get("vector_index_lifecycle_enabled") is True, "vector lifecycle must be enabled")
    assert_true(job_metrics.get("vector_index_derived") is True, "vector index must be marked derived")
    assert_true(job_metrics.get("vector_index_rebuildable") is True, "vector index must be rebuildable")
    assert_true(job_metrics.get("vector_index_persisted") is False, "vector index must not be persisted in 13.3")
    assert_true(job_metrics.get("vector_index_status") == "pending", "pending vector index status mismatch")

    run = request(
        "POST",
        base_url,
        f"/api/indexing/jobs/{job['id']}/run",
        {"force": True, "metrics": {"validation": "sprint-13-3-run"}},
    )
    run_metrics = run.get("metrics") or {}
    assert_true(run.get("status") == "succeeded", "derived vector lifecycle run should succeed")
    assert_true(run.get("indexed_chunk_count") == 2, "derived vector lifecycle should count source chunks")
    assert_true(run.get("failed_chunk_count") == 0, "derived vector lifecycle should not fail chunks")
    assert_true(run_metrics.get("index_target") == "vector_derived", "run index target mismatch")
    assert_true(run_metrics.get("index_source_of_truth") == "postgresql_chunks", "source of truth mismatch")
    assert_true(run_metrics.get("vector_index_status") == "ready_reference_only", "vector index status mismatch")
    assert_true(run_metrics.get("vector_index_source_chunk_count") == 2, "source chunk count mismatch")
    assert_true(run_metrics.get("vector_index_rebuild_strategy") == "rebuild_from_postgresql_chunks", "rebuild strategy mismatch")
    assert_true(run_metrics.get("vector_index_write_enabled") is False, "vector writes must be disabled in 13.3")
    assert_true(run_metrics.get("embedding_generated") is False, "embeddings must not be generated in 13.3")
    assert_true(run_metrics.get("embedding_execution_enabled") is False, "embedding execution must be disabled in 13.3")
    assert_true(run_metrics.get("vector_indexed") is False, "vector DB indexing must not execute in 13.3")
    assert_true(run_metrics.get("llm_used") is False, "index lifecycle must not use LLM")

    search = request(
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
    search_metrics = search.get("metrics") or {}
    assert_true(search_metrics.get("resolved_retrieval_mode") == "lexical_only", "hybrid must still fallback to lexical_only in 13.3")
    assert_true(search_metrics.get("retrieval_mode_fallback_reason") == "vector_provider_not_configured", "retrieval fallback reason mismatch")
    assert_true(search_metrics.get("vector_retrieval_enabled") is False, "vector retrieval must not execute in 13.3")

    return {
        "status": "passed",
        "organization_id": organization_id,
        "document_version_id": document_version_id,
        "indexing_job_id": job["id"],
        "index_target": run.get("index_target"),
        "index_status": run.get("status"),
        "indexed_chunk_count": run.get("indexed_chunk_count"),
        "vector_index_status": run_metrics.get("vector_index_status"),
        "vector_index_derived": run_metrics.get("vector_index_derived"),
        "vector_index_rebuildable": run_metrics.get("vector_index_rebuildable"),
        "vector_index_persisted": run_metrics.get("vector_index_persisted"),
        "vector_index_write_enabled": run_metrics.get("vector_index_write_enabled"),
        "embedding_generated": run_metrics.get("embedding_generated"),
        "vector_indexed": run_metrics.get("vector_indexed"),
        "hybrid_resolved_mode": search_metrics.get("resolved_retrieval_mode"),
        "hybrid_fallback_reason": search_metrics.get("retrieval_mode_fallback_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sprint 13.3 derived vector index lifecycle smoke validation.")
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
