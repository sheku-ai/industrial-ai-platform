#!/usr/bin/env python3
"""Manual smoke contract for Enterprise Search Runtime text/plain execution."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.enterprise_search_runtime import build_enterprise_search  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Industrial AI Platform enables governed enterprise search over published chunks.\n"
    "Enterprise search must work without embeddings, without Qdrant and without AI.\n\n"
    "The lexical search runtime ranks published chunks using deterministic token overlap."
)
CONTENT_TYPE = "text/plain"
QUERY = "enterprise search published chunks"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "enterprise-search-e2e-smoke",
        "runtime_state": "ready",
        "runtime_trace": {},
        "storage_provider_descriptor": provider_descriptor,
        "execution_flags": {
            "storage_provider_name": "memory",
            "storage_provider_type": "memory",
            "storage_provider_configured": True,
            "storage_provider_status": "configured",
            "object_stored": False,
            "file_uploaded": False,
            "checksum_calculated": False,
            "ingestion_executed": False,
            "chunks_created": False,
            "embeddings_created": False,
            "ai_required": False,
            "vector_store_required": False,
        },
    }


def _request(
    upload_session: dict[str, Any],
    operation: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_storage_execution_request(
        upload_session,
        requested_operation=operation,
        requested_by="enterprise-search-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"enterprise-search-e2e:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _expect(condition: bool, failures: list[str], message: str) -> bool:
    if condition:
        return True
    failures.append(message)
    return False


def main() -> int:
    failures: list[str] = []
    if SessionLocal is None:
        payload = {"passed": False, "failures": ["database url is not configured"]}
        print(json.dumps(payload, sort_keys=True))
        return 1

    upload_session = _upload_session()
    artifact_id = upload_session["artifact_id"]

    create_result = _request(upload_session, "create_object")
    object_handle = _object_handle(create_result)

    upload_result = _request(
        upload_session,
        "upload_object",
        metadata={
            "object_handle": object_handle,
            "content_text": CONTENT_TEXT,
            "content_type": CONTENT_TYPE,
            "metadata": {"source": "enterprise_search_e2e_smoke"},
        },
    )
    object_handle = _object_handle(upload_result) or object_handle

    verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
    handoff = build_document_processing_handoff(
        artifact_id=artifact_id,
        storage_execution_status=verify_result,
    )
    processing = build_document_processing_execution(handoff)
    processing_result = processing.get("processing_result") if isinstance(processing.get("processing_result"), dict) else {}
    parser_runtime = processing.get("parser_runtime") if isinstance(processing.get("parser_runtime"), dict) else {}
    chunk_generation = build_document_chunk_generation(processing_result)
    chunk_result = chunk_generation.get("chunk_result") if isinstance(chunk_generation.get("chunk_result"), dict) else chunk_generation
    publication = build_knowledge_publication(chunk_result)

    db = SessionLocal()
    try:
        knowledge_index = build_knowledge_index(db, publication)
        search = build_enterprise_search(db=db, query=QUERY, top_k=5)
    finally:
        db.close()

    results = search.get("results") if isinstance(search.get("results"), list) else []
    citations = search.get("citations") if isinstance(search.get("citations"), list) else []
    first_result = results[0] if results else {}
    first_trace = first_result.get("ranking_trace") if isinstance(first_result.get("ranking_trace"), dict) else {}
    first_citation = first_result.get("citation") if isinstance(first_result.get("citation"), dict) else {}

    storage_ok = all(
        (
            bool(verify_result.get("storage_verified")),
            bool(verify_result.get("processing_handoff_prerequisite_met")),
            object_handle is not None,
        )
    )
    handoff_ok = bool(handoff.get("processing_handoff_ready"))
    processing_ok = all(
        (
            processing.get("processing_status") == "completed",
            processing.get("processing_completed") is True,
            parser_runtime.get("parser_executed") is True,
        )
    )
    chunk_ok = all(
        (
            chunk_generation.get("chunk_generation_completed") is True,
            chunk_generation.get("chunks_created") is True,
        )
    )
    publication_ok = all(
        (
            publication.get("publication_completed") is True,
            publication.get("knowledge_published") is True,
        )
    )
    index_ok = all(
        (
            knowledge_index.get("index_completed") is True,
            knowledge_index.get("document_indexed") is True,
            knowledge_index.get("chunks_indexed") == publication.get("published_chunk_count"),
            knowledge_index.get("metadata_persisted") is True,
        )
    )
    search_ok = all(
        (
            search.get("search_completed") is True,
            search.get("search_succeeded") is True,
            int(search.get("result_count") or 0) >= 1,
            all(bool(result.get("search_result_id")) for result in results),
            all(bool(result.get("published_chunk_id")) for result in results),
            all(isinstance(result.get("citation"), dict) and result.get("citation") for result in results),
            all(bool(citation.get("citation_id")) for citation in citations),
            search.get("semantic_search_used") is False,
            search.get("embeddings_required") is False,
            search.get("ai_required") is False,
            search.get("search_uses_postgresql") is True,
            search.get("search_uses_postgresql_fts") is True,
        )
    )
    ranking_ok = all(
        (
            all(term in (first_result.get("text") or "").lower() for term in ("enterprise", "search", "published", "chunks")),
            float(first_result.get("score") or 0) > 0,
            bool(first_trace.get("ranking_model")),
            first_citation.get("source") in {"published_chunk", "knowledge_chunk"},
        )
    )

    _expect(storage_ok, failures, "storage verification must pass before processing")
    _expect(handoff_ok, failures, "processing handoff must become ready")
    _expect(processing_ok, failures, "processing runtime must parse text/plain payload")
    _expect(chunk_ok, failures, "chunk runtime must generate chunks")
    _expect(publication_ok, failures, "knowledge publication runtime must publish chunks")
    _expect(index_ok, failures, "knowledge index runtime must persist published chunks")
    _expect(search_ok, failures, "enterprise search runtime must return citation-ready lexical results")
    _expect(ranking_ok, failures, "first search result must include query terms with lexical ranking trace")

    payload = {
        "passed": all((storage_ok, handoff_ok, processing_ok, chunk_ok, publication_ok, index_ok, search_ok, ranking_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "processing_completed": bool(processing.get("processing_completed")),
        "parser_executed": bool(parser_runtime.get("parser_executed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "chunks_created": bool(chunk_generation.get("chunks_created")),
        "publication_completed": bool(publication.get("publication_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "document_indexed": bool(knowledge_index.get("document_indexed")),
        "chunks_indexed": knowledge_index.get("chunks_indexed"),
        "metadata_persisted": bool(knowledge_index.get("metadata_persisted")),
        "search_completed": bool(search.get("search_completed")),
        "search_succeeded": bool(search.get("search_succeeded")),
        "result_count": search.get("result_count"),
        "all_results_have_search_result_id": all(bool(result.get("search_result_id")) for result in results),
        "all_results_have_published_chunk_id": all(bool(result.get("published_chunk_id")) for result in results),
        "all_results_have_citation": all(isinstance(result.get("citation"), dict) and result.get("citation") for result in results),
        "all_citations_have_citation_id": all(bool(citation.get("citation_id")) for citation in citations),
        "first_result_contains_query_terms": bool(ranking_ok),
        "first_result_score": first_result.get("score"),
        "first_ranking_reasons": first_trace.get("lexical_reasons"),
        "first_ranking_model": first_trace.get("ranking_model"),
        "first_citation_source": first_citation.get("source"),
        "semantic_search_used": bool(search.get("semantic_search_used")),
        "embeddings_required": bool(search.get("embeddings_required")),
        "ai_required": bool(search.get("ai_required")),
        "search_uses_postgresql": bool(search.get("search_uses_postgresql")),
        "search_uses_postgresql_fts": bool(search.get("search_uses_postgresql_fts")),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
