#!/usr/bin/env python3
"""Manual smoke contract for Enterprise Search productization over PostgreSQL FTS."""

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

from app.db.session import SessionLocal  # noqa: E402
from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.enterprise_search_runtime import build_enterprise_search  # noqa: E402
from app.services.knowledge_fts_runtime import build_knowledge_fts_search  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Enterprise search productization exposes PostgreSQL full text search with pagination.\n"
    "The search product returns facets, highlighted snippets, ranking positions and citations.\n\n"
    "PostgreSQL remains the source of truth without external vector stores, semantic search or AI."
)
CONTENT_TYPE = "text/plain"
QUERY = "enterprise search productization facets pagination"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "enterprise-search-productization-smoke",
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


def _request(upload_session: dict[str, Any], operation: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_storage_execution_request(
        upload_session,
        requested_operation=operation,
        requested_by="enterprise-search-productization-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"enterprise-search-productization:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _records(readback: dict[str, Any], domain: str, record_type: str | None = None) -> list[dict[str, Any]]:
    records = [item for item in readback.get("records") or [] if item.get("runtime_domain") == domain]
    if record_type is not None:
        records = [item for item in records if item.get("record_type") == record_type]
    return records


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
            "metadata": {"source": "enterprise_search_productization_smoke"},
        },
    )
    object_handle = _object_handle(upload_result) or object_handle
    verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
    handoff = build_document_processing_handoff(artifact_id=artifact_id, storage_execution_status=verify_result)
    processing = build_document_processing_execution(handoff)
    processing_result = processing.get("processing_result") if isinstance(processing.get("processing_result"), dict) else {}
    chunk_generation = build_document_chunk_generation(processing_result)
    chunk_result = chunk_generation.get("chunk_result") if isinstance(chunk_generation.get("chunk_result"), dict) else chunk_generation
    publication = build_knowledge_publication(chunk_result)

    db = SessionLocal()
    try:
        knowledge_index = build_knowledge_index(db, publication)
        fts_search = build_knowledge_fts_search(db, query=QUERY, top_k=10, offset=0, limit=10, filters={"artifact_id": artifact_id})
        enterprise_search = build_enterprise_search(
            db=db,
            query=QUERY,
            top_k=10,
            offset=0,
            limit=10,
            include_facets=True,
            include_debug=True,
            search_config={"artifact_id": artifact_id, "content_type": CONTENT_TYPE},
        )
        persistence_execution_id = enterprise_search.get("runtime_persistence", {}).get("execution_id")
        persistence_readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    results = enterprise_search.get("results") if isinstance(enterprise_search.get("results"), list) else []
    citations = enterprise_search.get("citations") if isinstance(enterprise_search.get("citations"), list) else []
    first_result = results[0] if results else {}
    facets = enterprise_search.get("facets") if isinstance(enterprise_search.get("facets"), dict) else {}

    storage_ok = verify_result.get("storage_verified") is True
    processing_ok = processing.get("processing_completed") is True
    chunk_ok = chunk_generation.get("chunk_generation_completed") is True
    publication_ok = publication.get("knowledge_published") is True
    index_ok = knowledge_index.get("index_completed") is True
    fts_ok = fts_search.get("fts_search_completed") is True
    enterprise_ok = all(
        (
            enterprise_search.get("search_completed") is True,
            enterprise_search.get("search_succeeded") is True,
            enterprise_search.get("search_uses_postgresql") is True,
            enterprise_search.get("search_uses_postgresql_fts") is True,
            enterprise_search.get("semantic_search_used") is False,
            enterprise_search.get("embeddings_required") is False,
            enterprise_search.get("ai_required") is False,
            enterprise_search.get("ranking_model") == "postgres_ts_rank_cd_simple_v1",
            int(enterprise_search.get("total_count") or 0) >= 1,
            int(enterprise_search.get("result_count") or 0) >= 1,
            enterprise_search.get("offset") == 0,
            int(enterprise_search.get("limit") or 0) > 0,
            isinstance(enterprise_search.get("has_more"), bool),
        )
    )
    result_contract_ok = all(
        (
            float(first_result.get("score") or 0) > 0,
            all(bool(result.get("search_result_id")) for result in results),
            all(bool(result.get("ranking_position")) for result in results),
            all(bool(result.get("highlighted_snippet")) for result in results),
            all(isinstance(result.get("citation"), dict) and result.get("citation") for result in results),
            all(citation.get("source") == "knowledge_chunk" for citation in citations),
        )
    )
    facets_ok = all(
        (
            bool(facets),
            isinstance(facets.get("content_type"), list),
            any(item.get("value") == CONTENT_TYPE and int(item.get("count") or 0) >= 1 for item in facets.get("content_type") or []),
        )
    )
    persistence_ok = all(
        (
            persistence_readback.get("persistence_status") == "persisted",
            len(_records(persistence_readback, "enterprise_search", "search_result_set")) == 1,
            (_records(persistence_readback, "enterprise_search", "search_result_set")[0].get("summary") or {}).get("search_uses_postgresql_fts") is True,
        )
    ) if _records(persistence_readback, "enterprise_search", "search_result_set") else False

    _expect(storage_ok, failures, "storage must verify object")
    _expect(processing_ok, failures, "processing must complete")
    _expect(chunk_ok, failures, "chunk runtime must complete")
    _expect(publication_ok, failures, "knowledge publication must publish")
    _expect(index_ok, failures, "knowledge index must complete")
    _expect(fts_ok, failures, "FTS runtime must complete")
    _expect(enterprise_ok, failures, "Enterprise Search product response must complete with PostgreSQL FTS")
    _expect(result_contract_ok, failures, "Enterprise Search results must satisfy product contract")
    _expect(facets_ok, failures, "Enterprise Search facets must include content_type")
    _expect(persistence_ok, failures, "Enterprise Search runtime persistence must be readable")

    payload = {
        "passed": all((storage_ok, processing_ok, chunk_ok, publication_ok, index_ok, fts_ok, enterprise_ok, result_contract_ok, facets_ok, persistence_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_completed": bool(processing.get("processing_completed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "fts_search_completed": bool(fts_search.get("fts_search_completed")),
        "enterprise_search_completed": bool(enterprise_search.get("search_completed")),
        "enterprise_search_succeeded": bool(enterprise_search.get("search_succeeded")),
        "search_uses_postgresql": bool(enterprise_search.get("search_uses_postgresql")),
        "search_uses_postgresql_fts": bool(enterprise_search.get("search_uses_postgresql_fts")),
        "semantic_search_used": bool(enterprise_search.get("semantic_search_used")),
        "embeddings_required": bool(enterprise_search.get("embeddings_required")),
        "ai_required": bool(enterprise_search.get("ai_required")),
        "ranking_model": enterprise_search.get("ranking_model"),
        "total_count": enterprise_search.get("total_count"),
        "result_count": enterprise_search.get("result_count"),
        "offset": enterprise_search.get("offset"),
        "limit": enterprise_search.get("limit"),
        "has_more": enterprise_search.get("has_more"),
        "first_result_score": first_result.get("score"),
        "all_results_have_search_result_id": all(bool(result.get("search_result_id")) for result in results),
        "all_results_have_ranking_position": all(bool(result.get("ranking_position")) for result in results),
        "all_results_have_highlighted_snippet": all(bool(result.get("highlighted_snippet")) for result in results),
        "all_results_have_citation": all(isinstance(result.get("citation"), dict) and result.get("citation") for result in results),
        "all_citations_source_knowledge_chunk": all(citation.get("source") == "knowledge_chunk" for citation in citations),
        "facets_present": bool(facets),
        "content_type_facet_present": bool(facets_ok),
        "runtime_persistence": bool(persistence_ok),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
