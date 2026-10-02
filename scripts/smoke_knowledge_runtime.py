#!/usr/bin/env python3
"""Automated smoke validation for the Knowledge Runtime.

This script exercises the persisted runtime path without requiring an LLM,
embeddings, BGE, Qdrant, or any external inference provider.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


class SmokeFailure(RuntimeError):
    pass


def request(method: str, base_url: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise SmokeFailure(f"{method} {path} failed with {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"{method} {path} failed: {exc}") from exc


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def get_or_create_organization(base_url: str) -> str:
    organizations = request("GET", base_url, "/api/core/organizations")
    if organizations:
        return organizations[0]["id"]

    created = request(
        "POST",
        base_url,
        "/api/core/organizations",
        {
            "slug": "smoke-workspace",
            "name": "Smoke Workspace",
            "description": "Generic workspace created by automated smoke validation.",
            "status": "active",
            "config": {"created_by": "smoke_knowledge_runtime"},
        },
    )
    return created["id"]


def assert_highlighted_result(response: dict[str, Any], collection_key: str, count_metric: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("highlighting_enabled") is True, "highlighting was not enabled")
    assert_true(metrics.get("highlighter") == "deterministic_cpu_v1", "unexpected highlighter")
    assert_true(int(metrics.get(count_metric) or 0) >= 1, f"{count_metric} did not report highlighted items")

    items = response.get(collection_key) or []
    assert_true(len(items) >= 1, f"{collection_key} returned no items")
    highlight = ((items[0].get("metadata") or {}).get("highlight") or {})
    assert_true(bool(highlight.get("snippet")), "highlight snippet missing from first item")
    assert_true(highlight.get("highlighter") == "deterministic_cpu_v1", "unexpected item highlighter")
    assert_true("<mark>" in highlight.get("snippet", ""), "highlight snippet does not contain mark tag")


def assert_facets(response: dict[str, Any], stage: str, expected_field: str, expected_value: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("facets_enabled") is True, "facets were not enabled")
    assert_true(metrics.get("facet_engine") == "deterministic_metadata_v1", "unexpected facet engine")
    fields = metrics.get(f"{stage}_facet_fields") or []
    assert_true(expected_field in fields, f"{expected_field} facet field missing from {stage}")
    facets = metrics.get(f"{stage}_facets") or []
    target = next((facet for facet in facets if facet.get("field") == expected_field), None)
    assert_true(target is not None, f"{expected_field} facet missing from {stage}")
    buckets = target.get("buckets") or []
    assert_true(
        any(bucket.get("value") == expected_value and int(bucket.get("count") or 0) >= 1 for bucket in buckets),
        f"{expected_field} facet did not include expected bucket {expected_value}",
    )


def assert_rerank(response: dict[str, Any], collection_key: str, count_metric: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("reranking_enabled") is True, "reranking was not enabled")
    assert_true(metrics.get("reranking_mode") == "rules", "unexpected reranking mode")
    assert_true(metrics.get("reranker") == "deterministic_rules_v1", "unexpected reranker")
    assert_true(int(metrics.get(count_metric) or 0) >= 1, f"{count_metric} did not report reranked items")
    items = response.get(collection_key) or []
    assert_true(len(items) >= 1, f"{collection_key} returned no items for rerank validation")
    rerank = ((items[0].get("metadata") or {}).get("rerank") or {})
    assert_true(rerank.get("reranker") == "deterministic_rules_v1", "candidate rerank trace missing")
    assert_true("rules" in rerank, "candidate rerank rules missing")
    assert_true(float(rerank.get("final_score") or 0.0) >= 0.0, "invalid rerank final score")


def assert_query_metrics(response: dict[str, Any], endpoint: str) -> None:
    metrics = response.get("metrics") or {}
    assert_true(metrics.get("query_metrics_enabled") is True, "query metrics were not enabled")
    assert_true(metrics.get("query_metrics_version") == "deterministic_query_metrics_v1", "unexpected query metrics version")
    assert_true(bool(metrics.get("query_event_id")), "query_event_id missing")
    assert_true(bool(metrics.get("query_hash")), "query_hash missing")
    assert_true(bool(metrics.get("normalized_query_hash")), "normalized_query_hash missing")
    assert_true(metrics.get("query_text_recorded") is False, "raw query text must not be recorded in metrics")
    assert_true(metrics.get("normalized_query_text_recorded") is False, "normalized query text must not be recorded in metrics")
    assert_true(metrics.get("query_endpoint") == endpoint, "unexpected query endpoint metric")
    assert_true(metrics.get("query_metrics_persistence_enabled") is False, "query metrics persistence should be disabled")


def assert_extractive_answer(answer: dict[str, Any]) -> None:
    metrics = answer.get("metrics") or {}
    assert_true(answer.get("answer") is not None, "extractive answer should not be null")
    assert_true(metrics.get("answer_mode") == "extractive", "unexpected answer mode")
    assert_true(metrics.get("extractive_answer_enabled") is True, "extractive answer was not enabled")
    assert_true(metrics.get("extractive_builder") == "deterministic_extractive_v1", "unexpected extractive builder")
    assert_true(int(metrics.get("extractive_evidence_count") or 0) >= 1, "extractive evidence missing")
    assert_true(metrics.get("answer_generated") is False, "extractive answer must not be marked as generated")
    assert_true(metrics.get("llm_used") is False, "extractive answer must not use LLM")
    assert_true("[" in answer.get("answer", ""), "extractive answer should include citation keys")


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    run_id = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    organization_id = get_or_create_organization(base_url)
    validation_key = "sprint-11-6"

    health = request("GET", base_url, "/health")
    assert_true(health.get("status") == "ok", "health endpoint did not return ok")

    knowledge_status = request("GET", base_url, "/api/knowledge/status")
    assert_true(knowledge_status.get("version") == "1.3.1", "unexpected platform version")

    registration = request(
        "POST",
        base_url,
        "/api/ingestion/register",
        {
            "organization_id": organization_id,
            "title": f"Smoke Knowledge Runtime {run_id}",
            "source_type": "controlled_input",
            "source_ref": {"smoke_run_id": run_id},
            "external_reference": f"smoke-knowledge-runtime-{run_id}",
            "description": "Automated generic smoke validation record.",
            "metadata": {"validation": validation_key, "smoke_run_id": run_id},
            "classification": {},
            "requested_by": "smoke_knowledge_runtime",
            "file_name": f"smoke-{run_id}.txt",
            "content_type": "text/plain",
        },
    )
    document_version_id = registration["document_version_id"]
    assert_true(registration["job_status"] == "pending", "ingestion job was not created as pending")

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
                    "text": "PostgreSQL is the source of truth for the platform knowledge runtime.",
                    "metadata": {"validation": validation_key, "smoke_run_id": run_id},
                    "quality": {"smoke": True, "validated": True},
                },
                {
                    "chunk_index": 1,
                    "text": "The Knowledge Runtime can return context and citations without an LLM provider.",
                    "metadata": {"validation": validation_key, "smoke_run_id": run_id},
                    "quality": {"smoke": True},
                },
            ],
        },
    )
    assert_true(chunks["chunk_count"] == 2, "expected two persisted chunks")
    assert_true(chunks["metrics"].get("llm_used") is False, "chunk persistence must not use LLM")

    indexing_job = request(
        "POST",
        base_url,
        "/api/indexing/jobs",
        {
            "organization_id": organization_id,
            "document_version_id": document_version_id,
            "index_target": "postgres_fts",
            "metrics": {"validation": validation_key, "smoke_run_id": run_id},
        },
    )
    indexing_run = request(
        "POST",
        base_url,
        f"/api/indexing/jobs/{indexing_job['id']}/run",
        {"force": True, "metrics": {"validation": validation_key}},
    )
    assert_true(indexing_run["status"] == "succeeded", "indexing job did not succeed")
    assert_true(indexing_run["indexed_chunk_count"] >= 2, "indexing did not process expected chunks")
    assert_true(indexing_run["metrics"].get("llm_used") is False, "indexing must not use LLM")

    common_search_payload = {
        "organization_id": organization_id,
        "query_text": query_text,
        "top_k": 5,
        "candidate_k": 10,
        "facet_fields": ["content_type", "metadata.validation"],
    }

    search = request("POST", base_url, "/api/knowledge/search", common_search_payload)
    assert_true(len(search["candidates"]) >= 1, "knowledge search returned no candidates")
    assert_true(search["metrics"].get("retrieval_provider") == "postgres_fts", "unexpected retrieval provider")
    assert_true(search["metrics"].get("query_normalized") is True, "query normalization was not applied")
    assert_true(search["metrics"].get("query_normalizer") == "deterministic_cpu_v1", "unexpected query normalizer")
    assert_true(search["metrics"].get("llm_used") is not True, "search must not use LLM")
    assert_highlighted_result(search, "candidates", "returned_candidates_highlighted_count")
    assert_facets(search, "retrieved_candidates", "metadata.validation", validation_key)
    assert_rerank(search, "candidates", "returned_candidates_reranked_count")
    assert_query_metrics(search, "search")

    context = request("POST", base_url, "/api/knowledge/context", {**common_search_payload, "enable_diversity": True})
    assert_true(len(context["context"]) >= 1, "context builder returned no context")
    assert_true(len(context["citations"]) >= 1, "citation builder returned no citations")
    assert_highlighted_result(context, "context", "selected_context_highlighted_count")
    assert_facets(context, "retrieved_candidates", "metadata.validation", validation_key)
    assert_facets(context, "selected_context", "metadata.validation", validation_key)
    assert_rerank(context, "context", "selected_context_reranked_count")
    assert_query_metrics(context, "context")

    answer = request("POST", base_url, "/api/knowledge/answer", {**common_search_payload, "use_inference": True})
    metrics = answer["metrics"]
    assert_extractive_answer(answer)
    assert_true(len(answer["context"]) >= 1, "answer endpoint returned no context")
    assert_true(len(answer["citations"]) >= 1, "answer endpoint returned no citations")
    assert_true(metrics.get("inference_enabled") is False, "inference must be disabled")
    assert_true(metrics.get("reason") == "extractive_answer_no_generation", "unexpected fallback reason")
    assert_highlighted_result(answer, "context", "selected_context_highlighted_count")
    assert_facets(answer, "retrieved_candidates", "metadata.validation", validation_key)
    assert_facets(answer, "selected_context", "metadata.validation", validation_key)
    assert_rerank(answer, "context", "selected_context_reranked_count")
    assert_query_metrics(answer, "answer")

    feedback = request(
        "POST",
        base_url,
        "/api/knowledge/feedback",
        {
            "organization_id": organization_id,
            "query_event_id": metrics.get("query_event_id"),
            "target_type": "answer",
            "target_id": metrics.get("query_event_id"),
            "rating": "positive",
            "comment": "Smoke validation feedback.",
            "metadata": {"validation": validation_key, "smoke_run_id": run_id},
        },
    )
    receipt = feedback.get("receipt") or {}
    assert_true(feedback.get("status") == "accepted", "feedback was not accepted")
    assert_true(receipt.get("feedback_received") is True, "feedback receipt missing")
    assert_true(receipt.get("feedback_status") == "accepted_not_persisted", "unexpected feedback status")
    assert_true(receipt.get("feedback_persistence_enabled") is False, "feedback persistence should be disabled")
    assert_true(receipt.get("comment_recorded") is True, "feedback comment signal missing")
    assert_true(receipt.get("comment_text_persisted") is False, "feedback comment text must not be persisted")

    return {
        "status": "passed",
        "run_id": run_id,
        "organization_id": organization_id,
        "document_version_id": document_version_id,
        "ingestion_job_id": registration["ingestion_job_id"],
        "indexing_job_id": indexing_job["id"],
        "candidate_count": len(search["candidates"]),
        "context_count": len(answer["context"]),
        "citation_count": len(answer["citations"]),
        "retrieval_provider": metrics.get("retrieval_provider"),
        "query_normalized": metrics.get("query_normalized"),
        "query_metrics_enabled": metrics.get("query_metrics_enabled"),
        "query_event_id": metrics.get("query_event_id"),
        "query_text_recorded": metrics.get("query_text_recorded"),
        "highlighting_enabled": metrics.get("highlighting_enabled"),
        "facets_enabled": metrics.get("facets_enabled"),
        "reranking_enabled": metrics.get("reranking_enabled"),
        "answer_mode": metrics.get("answer_mode"),
        "extractive_answer_enabled": metrics.get("extractive_answer_enabled"),
        "extractive_evidence_count": metrics.get("extractive_evidence_count"),
        "feedback_received": receipt.get("feedback_received"),
        "feedback_persistence_enabled": receipt.get("feedback_persistence_enabled"),
        "answer_generated": metrics.get("answer_generated"),
        "inference_enabled": metrics.get("inference_enabled"),
        "llm_used": metrics.get("llm_used"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Knowledge Runtime smoke validation.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--query", default="PostgreSQL   source   of truth")
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
