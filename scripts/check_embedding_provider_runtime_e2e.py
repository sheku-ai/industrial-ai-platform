#!/usr/bin/env python3
"""Manual smoke contract for Embedding Provider Runtime Framework."""

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
from app.services.embedding_provider_registry import get_embedding_provider_registry  # noqa: E402
from app.services.embedding_runtime import build_embedding_runtime  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = "Embedding provider framework selects the metadata-only reference provider without generating vectors."
CONTENT_TYPE = "text/plain"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "embedding-provider-runtime-e2e-smoke",
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
        requested_by="embedding-provider-runtime-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"embedding-provider-runtime-e2e:{operation}",
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

    registry_health = get_embedding_provider_registry().health()
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
        persistence_execution_id = (embedding.get("runtime_persistence") or {}).get("execution_id")
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    provider_registry_loaded = registry_health.get("provider_registry_loaded") is True
    metadata_provider_selected = embedding.get("metadata_provider_selected") is True
    provider_runtime_called = embedding.get("provider_runtime_called") is True
    provider_name_ok = embedding.get("provider_name") == "metadata-only"
    provider_type_ok = embedding.get("provider_type") == "reference"
    provider_generated_vector_ok = embedding.get("provider_generated_vector") is False
    embedding_record_created = embedding.get("embedding_record_created") is True
    runtime_persistence = all(
        (
            (embedding.get("runtime_persistence") or {}).get("persistence_completed") is True,
            readback.get("persistence_status") == "persisted",
            (readback.get("domains") or {}).get("embedding_runtime", 0) >= 1,
        )
    )
    semantic_search_used = bool(embedding.get("semantic_search_used"))
    postgresql_source_of_truth = embedding.get("postgresql_source_of_truth") is True

    _expect(provider_registry_loaded, failures, "provider registry must load")
    _expect(metadata_provider_selected, failures, "metadata-only provider must be selected")
    _expect(provider_runtime_called, failures, "provider runtime adapter must be called")
    _expect(provider_name_ok, failures, "provider_name must be metadata-only")
    _expect(provider_type_ok, failures, "provider_type must be reference")
    _expect(provider_generated_vector_ok, failures, "provider must not generate a vector")
    _expect(embedding_record_created, failures, "embedding record must be created")
    _expect(runtime_persistence, failures, "embedding runtime persistence must be persisted")
    _expect(not semantic_search_used, failures, "semantic search must remain disabled")
    _expect(postgresql_source_of_truth, failures, "PostgreSQL must remain source of truth")

    payload = {
        "provider_registry_loaded": provider_registry_loaded,
        "metadata_provider_selected": metadata_provider_selected,
        "provider_runtime_called": provider_runtime_called,
        "provider_name": embedding.get("provider_name"),
        "provider_type": embedding.get("provider_type"),
        "provider_generated_vector": bool(embedding.get("provider_generated_vector")),
        "embedding_record_created": bool(embedding.get("embedding_record_created")),
        "runtime_persistence": bool(runtime_persistence),
        "semantic_search_used": semantic_search_used,
        "postgresql_source_of_truth": postgresql_source_of_truth,
        "passed": all(
            (
                provider_registry_loaded,
                metadata_provider_selected,
                provider_runtime_called,
                provider_name_ok,
                provider_type_ok,
                provider_generated_vector_ok,
                embedding_record_created,
                runtime_persistence,
                not semantic_search_used,
                postgresql_source_of_truth,
            )
        )
        and not failures,
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
