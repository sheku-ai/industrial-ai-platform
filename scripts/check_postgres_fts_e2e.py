#!/usr/bin/env python3
"""Manual smoke contract for PostgreSQL FTS over the persistent Knowledge Index."""

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
from app.services.knowledge_fts_runtime import build_knowledge_fts_health, build_knowledge_fts_search  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_lifecycle_runtime import build_knowledge_lifecycle  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "PostgreSQL full text search indexes persistent knowledge chunks with native ranking.\n"
    "The knowledge chunk contains searchable maintenance-free lexical content for FTS.\n\n"
    "Highlighted snippets and citation-ready ranked results are produced without embeddings or AI."
)
CONTENT_TYPE = "text/plain"
QUERY = "persistent knowledge chunks native ranking"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "postgres-fts-e2e-smoke",
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
        requested_by="postgres-fts-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"postgres-fts-e2e:{operation}",
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
            "metadata": {"source": "postgres_fts_e2e_smoke"},
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
        lifecycle = build_knowledge_lifecycle(db, operation="reindex", mode="ARTIFACT", artifact_id=artifact_id)
        fts_health = build_knowledge_fts_health(db)
        fts_search = build_knowledge_fts_search(db, query=QUERY, top_k=5, filters={"artifact_id": artifact_id})
        enterprise_search = build_enterprise_search(db=db, query=QUERY, top_k=5, search_config={"artifact_id": artifact_id})
        persistence_execution_id = fts_search.get("runtime_persistence", {}).get("execution_id")
        persistence_readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    fts_results = fts_search.get("results") if isinstance(fts_search.get("results"), list) else []
    fts_citations = fts_search.get("citations") if isinstance(fts_search.get("citations"), list) else []
    first_result = fts_results[0] if fts_results else {}
    storage_ok = verify_result.get("storage_verified") is True
    processing_ok = processing.get("processing_completed") is True
    chunk_ok = chunk_generation.get("chunk_generation_completed") is True
    publication_ok = publication.get("knowledge_published") is True
    index_ok = knowledge_index.get("index_completed") is True
    lifecycle_ok = all(
        (
            lifecycle.get("lifecycle_completed") is True,
            int(lifecycle.get("health", {}).get("indexed_documents") or 0) >= 1,
            int(lifecycle.get("health", {}).get("indexed_chunks") or 0) >= 1,
        )
    )
    fts_projection_ok = all(
        (
            fts_health.get("fts_index_created") is True,
            fts_search.get("fts_projection", {}).get("fts_index_created") is True,
            fts_search.get("fts_projection", {}).get("fts_backfill_completed") is True,
        )
    )
    fts_search_ok = all(
        (
            fts_search.get("fts_search_completed") is True,
            fts_search.get("fts_search_succeeded") is True,
            fts_search.get("search_uses_postgresql") is True,
            fts_search.get("search_uses_postgresql_fts") is True,
            fts_search.get("semantic_search_used") is False,
            fts_search.get("embeddings_required") is False,
            fts_search.get("ai_required") is False,
            int(fts_search.get("result_count") or 0) >= 1,
            float(first_result.get("score") or 0) > 0,
            bool(first_result.get("highlighted_snippet")),
            all(isinstance(result.get("citation"), dict) and result.get("citation") for result in fts_results),
            all(citation.get("source") == "knowledge_chunk" for citation in fts_citations),
        )
    )
    enterprise_ok = all(
        (
            enterprise_search.get("search_completed") is True,
            enterprise_search.get("search_succeeded") is True,
            enterprise_search.get("search_uses_postgresql") is True,
            enterprise_search.get("search_uses_postgresql_fts") is True,
            enterprise_search.get("semantic_search_used") is False,
            enterprise_search.get("ai_required") is False,
        )
    )
    persistence_ok = all(
        (
            persistence_readback.get("persistence_status") == "persisted",
            len(_records(persistence_readback, "knowledge_fts", "fts_result_set")) == 1,
            len(_records(persistence_readback, "knowledge_fts", "fts_result")) >= 1,
        )
    )

    _expect(storage_ok, failures, "storage must verify object")
    _expect(processing_ok, failures, "processing must complete")
    _expect(chunk_ok, failures, "chunk runtime must complete")
    _expect(publication_ok, failures, "knowledge publication must publish chunks")
    _expect(index_ok, failures, "knowledge index must complete")
    _expect(lifecycle_ok, failures, "knowledge lifecycle must report healthy indexed records")
    _expect(fts_projection_ok, failures, "PostgreSQL FTS projection and backfill must be ready")
    _expect(fts_search_ok, failures, "PostgreSQL FTS must return ranked highlighted citation-ready results")
    _expect(enterprise_ok, failures, "Enterprise Search must use PostgreSQL FTS")
    _expect(persistence_ok, failures, "knowledge_fts runtime persistence must be readable")

    payload = {
        "passed": all((storage_ok, processing_ok, chunk_ok, publication_ok, index_ok, lifecycle_ok, fts_projection_ok, fts_search_ok, enterprise_ok, persistence_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_completed": bool(processing.get("processing_completed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "lifecycle_healthy": bool(lifecycle_ok),
        "fts_index_created": bool(fts_search.get("fts_projection", {}).get("fts_index_created")),
        "fts_backfill_completed": bool(fts_search.get("fts_projection", {}).get("fts_backfill_completed")),
        "fts_search_completed": bool(fts_search.get("fts_search_completed")),
        "fts_search_succeeded": bool(fts_search.get("fts_search_succeeded")),
        "search_uses_postgresql": bool(fts_search.get("search_uses_postgresql")),
        "search_uses_postgresql_fts": bool(fts_search.get("search_uses_postgresql_fts")),
        "semantic_search_used": bool(fts_search.get("semantic_search_used")),
        "embeddings_required": bool(fts_search.get("embeddings_required")),
        "ai_required": bool(fts_search.get("ai_required")),
        "result_count": fts_search.get("result_count"),
        "first_result_score": first_result.get("score"),
        "highlighted_snippet_present": bool(first_result.get("highlighted_snippet")),
        "all_results_have_citation": all(isinstance(result.get("citation"), dict) and result.get("citation") for result in fts_results),
        "all_citations_source_knowledge_chunk": all(citation.get("source") == "knowledge_chunk" for citation in fts_citations),
        "runtime_persistence": bool(persistence_ok),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
