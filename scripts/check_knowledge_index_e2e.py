#!/usr/bin/env python3
"""Manual smoke contract for Knowledge Index Foundation."""

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
from app.services.knowledge_index_runtime import (  # noqa: E402
    build_knowledge_index,
    read_knowledge_chunk,
    read_knowledge_document,
)
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Knowledge index foundation persists published chunks as durable knowledge documents.\n"
    "Enterprise search reads the knowledge repository without embeddings, Qdrant or AI.\n\n"
    "Incremental indexing is idempotent and safe to reindex without duplicate chunks."
)
CONTENT_TYPE = "text/plain"
QUERY = "knowledge repository published chunks"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "knowledge-index-e2e-smoke",
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
        requested_by="knowledge-index-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"knowledge-index-e2e:{operation}",
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
            "metadata": {"source": "knowledge_index_e2e_smoke"},
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
        first_index = build_knowledge_index(db, publication)
        second_index = build_knowledge_index(db, publication)
        knowledge_document = first_index.get("knowledge_document") if isinstance(first_index.get("knowledge_document"), dict) else {}
        indexed_chunks = first_index.get("knowledge_chunks") if isinstance(first_index.get("knowledge_chunks"), list) else []
        first_chunk = indexed_chunks[0] if indexed_chunks else {}
        document_id = knowledge_document.get("knowledge_document_id")
        chunk_id = first_chunk.get("knowledge_chunk_id")
        document_readback = read_knowledge_document(db, str(document_id)) if document_id else None
        chunk_readback = read_knowledge_chunk(db, str(chunk_id)) if chunk_id else None
        search = build_enterprise_search(db=db, query=QUERY, top_k=5)
    finally:
        db.close()

    results = search.get("results") if isinstance(search.get("results"), list) else []
    first_document_readback = document_readback or {}
    readback_chunks = first_document_readback.get("chunks") if isinstance(first_document_readback.get("chunks"), list) else []
    search_metadata_ok = all(
        isinstance(result.get("metadata"), dict) and bool(result.get("metadata", {}).get("knowledge_chunk_id"))
        for result in results
    )

    storage_ok = bool(verify_result.get("storage_verified"))
    handoff_ok = bool(handoff.get("processing_handoff_ready"))
    processing_ok = all((processing.get("processing_completed") is True, parser_runtime.get("parser_executed") is True))
    chunk_ok = all((chunk_generation.get("chunk_generation_completed") is True, chunk_generation.get("chunks_created") is True))
    publication_ok = all((publication.get("publication_completed") is True, publication.get("knowledge_published") is True))
    index_ok = all(
        (
            first_index.get("index_completed") is True,
            first_index.get("document_indexed") is True,
            first_index.get("chunks_indexed") == publication.get("published_chunk_count"),
            first_index.get("metadata_persisted") is True,
            bool(first_document_readback),
            bool(chunk_readback),
            len(readback_chunks) == int(publication.get("published_chunk_count") or 0),
        )
    )
    idempotency_ok = all(
        (
            second_index.get("index_completed") is True,
            second_index.get("idempotent") is True,
            second_index.get("chunks_created") == 0,
            second_index.get("chunks_updated") == 0,
            second_index.get("chunks_superseded") == 0,
            second_index.get("knowledge_document", {}).get("version") == first_index.get("knowledge_document", {}).get("version"),
        )
    )
    search_ok = all(
        (
            search.get("search_completed") is True,
            search.get("search_succeeded") is True,
            int(search.get("result_count") or 0) >= 1,
            search_metadata_ok,
            search.get("semantic_search_used") is False,
            search.get("embeddings_required") is False,
            search.get("ai_required") is False,
        )
    )

    _expect(storage_ok, failures, "storage runtime must verify object")
    _expect(handoff_ok, failures, "processing handoff must become ready")
    _expect(processing_ok, failures, "processing runtime must parse text/plain payload")
    _expect(chunk_ok, failures, "chunk runtime must generate chunks")
    _expect(publication_ok, failures, "knowledge publication runtime must publish chunks")
    _expect(index_ok, failures, "knowledge index runtime must persist and read back knowledge records")
    _expect(idempotency_ok, failures, "knowledge index runtime must be idempotent on repeated indexing")
    _expect(search_ok, failures, "enterprise search runtime must read indexed PostgreSQL knowledge chunks")

    payload = {
        "passed": all((storage_ok, handoff_ok, processing_ok, chunk_ok, publication_ok, index_ok, idempotency_ok, search_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "processing_completed": bool(processing.get("processing_completed")),
        "parser_executed": bool(parser_runtime.get("parser_executed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "chunks_created": bool(chunk_generation.get("chunks_created")),
        "publication_completed": bool(publication.get("publication_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(first_index.get("index_completed")),
        "document_indexed": bool(first_index.get("document_indexed")),
        "chunks_indexed": first_index.get("chunks_indexed"),
        "metadata_persisted": bool(first_index.get("metadata_persisted")),
        "document_readback": bool(document_readback),
        "chunk_readback": bool(chunk_readback),
        "idempotent": bool(second_index.get("idempotent")),
        "reindex_without_duplicates": bool(idempotency_ok),
        "search_completed": bool(search.get("search_completed")),
        "search_succeeded": bool(search.get("search_succeeded")),
        "result_count": search.get("result_count"),
        "search_uses_postgresql": bool(search_metadata_ok),
        "semantic_search_used": bool(search.get("semantic_search_used")),
        "embeddings_required": bool(search.get("embeddings_required")),
        "ai_required": bool(search.get("ai_required")),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
