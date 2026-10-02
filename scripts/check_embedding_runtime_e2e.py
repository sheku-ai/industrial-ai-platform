#!/usr/bin/env python3
"""Manual smoke contract for Optional Embedding Runtime Foundation."""

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
from app.services.embedding_runtime import build_embedding_runtime  # noqa: E402
from app.services.enterprise_search_runtime import build_enterprise_search  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Optional embedding runtime stores deterministic embedding metadata as a derived artifact.\n"
    "PostgreSQL remains the source of truth and semantic search is not executed in this foundation."
)
CONTENT_TYPE = "text/plain"
QUERY = "embedding runtime metadata"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "embedding-runtime-e2e-smoke",
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
        requested_by="embedding-runtime-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"embedding-runtime-e2e:{operation}",
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
            "metadata": {"source": "embedding_runtime_e2e_smoke"},
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
        chunks = knowledge_index.get("knowledge_chunks") if isinstance(knowledge_index.get("knowledge_chunks"), list) else []
        chunk_id = chunks[0].get("knowledge_chunk_id") if chunks and isinstance(chunks[0], dict) else None
        embedding = build_embedding_runtime(
            db,
            chunk_id=str(chunk_id),
            model_name="metadata-only",
            model_version="metadata-only/1.0",
            embedding_dimensions=0,
            runtime_metadata={"source": "embedding_runtime_e2e_smoke"},
        ) if chunk_id else {}
        search = build_enterprise_search(db=db, query=QUERY, top_k=5)
        persistence_execution_id = (embedding.get("runtime_persistence") or {}).get("execution_id")
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    storage_ok = verify_result.get("storage_verified") is True
    processing_ok = processing.get("processing_completed") is True
    chunk_ok = chunk_generation.get("chunk_generation_completed") is True
    publication_ok = publication.get("knowledge_published") is True
    index_ok = knowledge_index.get("index_completed") is True
    embedding_ok = all(
        (
            embedding.get("embedding_runtime_prepared") is True,
            embedding.get("embedding_record_created") is True,
            embedding.get("embedding_metadata_persisted") is True,
            embedding.get("embedding_vector_generated") is False,
            embedding.get("embedding_provider_called") is False,
            embedding.get("semantic_search_used") is False,
            embedding.get("postgresql_source_of_truth") is True,
        )
    )
    persistence_ok = all(
        (
            (embedding.get("runtime_persistence") or {}).get("persistence_completed") is True,
            readback.get("persistence_status") == "persisted",
            (readback.get("domains") or {}).get("embedding_runtime", 0) >= 1,
        )
    )
    search_ok = all(
        (
            search.get("search_completed") is True,
            search.get("search_uses_postgresql") is True,
            search.get("search_uses_postgresql_fts") is True,
            search.get("semantic_search_used") is False,
            search.get("embeddings_required") is False,
        )
    )

    _expect(storage_ok, failures, "storage must be verified")
    _expect(processing_ok, failures, "processing must complete")
    _expect(chunk_ok, failures, "chunk generation must complete")
    _expect(publication_ok, failures, "knowledge publication must complete")
    _expect(index_ok, failures, "knowledge index must complete")
    _expect(embedding_ok, failures, "embedding metadata runtime must persist metadata without vectors")
    _expect(persistence_ok, failures, "embedding runtime persistence must be readable")
    _expect(search_ok, failures, "enterprise search must remain PostgreSQL FTS only")

    payload = {
        "passed": all((storage_ok, processing_ok, chunk_ok, publication_ok, index_ok, embedding_ok, persistence_ok, search_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_completed": bool(processing.get("processing_completed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "embedding_runtime_prepared": bool(embedding.get("embedding_runtime_prepared")),
        "embedding_record_created": bool(embedding.get("embedding_record_created")),
        "embedding_metadata_persisted": bool(embedding.get("embedding_metadata_persisted")),
        "embedding_vector_generated": bool(embedding.get("embedding_vector_generated")),
        "embedding_provider_called": bool(embedding.get("embedding_provider_called")),
        "semantic_search_used": bool(embedding.get("semantic_search_used") or search.get("semantic_search_used")),
        "postgresql_source_of_truth": bool(embedding.get("postgresql_source_of_truth")),
        "runtime_persistence": bool(persistence_ok),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
