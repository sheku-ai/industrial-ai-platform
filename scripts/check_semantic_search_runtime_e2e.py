#!/usr/bin/env python3
"""Manual smoke contract for descriptor-only Semantic Search Runtime foundation."""

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
from app.services.semantic_search_runtime import build_semantic_search_runtime  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402
from app.services.vector_index_runtime import build_vector_index_runtime  # noqa: E402


CONTENT_TEXT = "Semantic search runtime foundation remains descriptor-only and PostgreSQL-authoritative."
CONTENT_TYPE = "text/plain"
QUERY = "semantic search runtime foundation"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "semantic-search-runtime-e2e-smoke",
        "runtime_state": "ready",
        "runtime_trace": {},
        "storage_provider_descriptor": InMemoryStorageProvider().descriptor.as_dict(),
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
        requested_by="semantic-search-runtime-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"semantic-search-runtime-e2e:{operation}",
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
        metadata={"object_handle": object_handle, "content_text": CONTENT_TEXT, "content_type": CONTENT_TYPE},
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
            provider_name="metadata-only",
            model_name="metadata-only",
            model_version="metadata-only/1.0",
            embedding_dimensions=0,
        ) if chunk_id else {}
        embedding_record = embedding.get("embedding_record") if isinstance(embedding.get("embedding_record"), dict) else {}
        vector_index = build_vector_index_runtime(
            db,
            embedding_id=str(embedding_record.get("embedding_id")),
            index_provider="qdrant-disabled",
            index_provider_type="descriptor-only",
            qdrant_provider_name="qdrant-disabled",
            qdrant_collection_name="derived-vector-index",
        ) if embedding_record.get("embedding_id") else {}
        vector_index_record = vector_index.get("vector_index_record") if isinstance(vector_index.get("vector_index_record"), dict) else {}
        semantic_search = build_semantic_search_runtime(
            db,
            query=QUERY,
            vector_index_id=str(vector_index_record.get("vector_index_id")),
            qdrant_provider_name="qdrant-disabled",
        ) if vector_index_record.get("vector_index_id") else {}
        enterprise_search = build_enterprise_search(db=db, query=QUERY, top_k=5)
        persistence_execution_id = (semantic_search.get("runtime_persistence") or {}).get("execution_id")
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    observed = {
        "storage_verified": verify_result.get("storage_verified") is True,
        "processing_completed": processing.get("processing_completed") is True,
        "chunk_generation_completed": chunk_generation.get("chunk_generation_completed") is True,
        "knowledge_published": publication.get("knowledge_published") is True,
        "index_completed": knowledge_index.get("index_completed") is True,
        "embedding_record_created": embedding.get("embedding_record_created") is True,
        "vector_index_record_created": vector_index.get("vector_index_record_created") is True,
        "qdrant_disabled_provider_selected": vector_index.get("qdrant_provider_name") == "qdrant-disabled",
        "semantic_search_runtime_prepared": semantic_search.get("semantic_search_runtime_prepared") is True,
        "semantic_search_enabled": bool(semantic_search.get("semantic_search_enabled")),
        "semantic_search_executed": bool(semantic_search.get("semantic_search_executed")),
        "vector_search_executed": bool(semantic_search.get("vector_search_executed")),
        "qdrant_called": bool(semantic_search.get("qdrant_called")),
        "network_call_attempted": bool(semantic_search.get("network_call_attempted")),
        "hybrid_search_enabled": bool(semantic_search.get("hybrid_search_enabled")),
        "enterprise_search_still_uses_postgresql_fts": enterprise_search.get("search_uses_postgresql_fts") is True
        and enterprise_search.get("semantic_search_used") is False,
        "postgresql_source_of_truth": semantic_search.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (semantic_search.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("semantic_search_runtime", 0) >= 1,
    }
    expectations = {
        "storage_verified": observed["storage_verified"] is True,
        "processing_completed": observed["processing_completed"] is True,
        "chunk_generation_completed": observed["chunk_generation_completed"] is True,
        "knowledge_published": observed["knowledge_published"] is True,
        "index_completed": observed["index_completed"] is True,
        "embedding_record_created": observed["embedding_record_created"] is True,
        "vector_index_record_created": observed["vector_index_record_created"] is True,
        "qdrant_disabled_provider_selected": observed["qdrant_disabled_provider_selected"] is True,
        "semantic_search_runtime_prepared": observed["semantic_search_runtime_prepared"] is True,
        "semantic_search_enabled": observed["semantic_search_enabled"] is False,
        "semantic_search_executed": observed["semantic_search_executed"] is False,
        "vector_search_executed": observed["vector_search_executed"] is False,
        "qdrant_called": observed["qdrant_called"] is False,
        "network_call_attempted": observed["network_call_attempted"] is False,
        "hybrid_search_enabled": observed["hybrid_search_enabled"] is False,
        "enterprise_search_still_uses_postgresql_fts": observed["enterprise_search_still_uses_postgresql_fts"] is True,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "semantic_search_enabled": False,
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "hybrid_search_enabled": False,
    }
    for key, value in expectations.items():
        expected = expected_values.get(key, True)
        _expect(bool(value), failures, f"{key} must be {str(expected).lower()}")
    payload = {**observed, "passed": all(expectations.values()) and not failures, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
