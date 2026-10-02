#!/usr/bin/env python3
"""Manual smoke contract for Knowledge Lifecycle & Indexing Runtime."""

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
from app.models.knowledge_index import KnowledgeChunk  # noqa: E402
from app.repositories.knowledge_index import KnowledgeIndexRepository  # noqa: E402
from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.enterprise_search_runtime import build_enterprise_search  # noqa: E402
from app.services.knowledge_lifecycle_runtime import (  # noqa: E402
    build_knowledge_index_health,
    build_knowledge_index_statistics,
    build_knowledge_lifecycle,
)
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TYPE = "text/plain"
QUERY = "knowledge lifecycle searchable chunk"


def _upload_session(artifact_id: str) -> dict[str, Any]:
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "knowledge-lifecycle-e2e-smoke",
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
        requested_by="knowledge-lifecycle-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"knowledge-lifecycle-e2e:{upload_session['artifact_id']}:{operation}:{uuid.uuid4()}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _publication_for_text(*, artifact_id: str, text: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    upload_session = _upload_session(artifact_id)
    create_result = _request(upload_session, "create_object")
    object_handle = _object_handle(create_result)
    upload_result = _request(
        upload_session,
        "upload_object",
        metadata={
            "object_handle": object_handle,
            "content_text": text,
            "content_type": CONTENT_TYPE,
            "metadata": {"source": "knowledge_lifecycle_e2e_smoke"},
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
    return verify_result, processing, publication


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

    artifact_id = str(uuid.uuid4())
    initial_text = (
        "Knowledge lifecycle searchable chunk manages initial indexing and incremental updates.\n"
        "The lifecycle runtime keeps persistent knowledge documents maintainable without AI."
    )
    updated_text = (
        "Knowledge lifecycle searchable chunk manages publication updates and selective reindex.\n"
        "Cleanup removes stale duplicate records while enterprise search remains consistent."
    )

    verify_result, processing, initial_publication = _publication_for_text(artifact_id=artifact_id, text=initial_text)
    _verify_update, _processing_update, updated_publication = _publication_for_text(artifact_id=artifact_id, text=updated_text)

    db = SessionLocal()
    try:
        initial = build_knowledge_lifecycle(
            db,
            operation="initial_indexing",
            mode="INCREMENTAL",
            publication_result=initial_publication,
        )
        incremental_ignore = build_knowledge_lifecycle(
            db,
            operation="incremental",
            mode="INCREMENTAL",
            publication_result=initial_publication,
        )
        publication_update = build_knowledge_lifecycle(
            db,
            operation="incremental",
            mode="INCREMENTAL",
            publication_result=updated_publication,
        )
        repository = KnowledgeIndexRepository(db)
        documents = repository.list_documents(artifact_id=artifact_id, include_inactive=True)
        selected_document_id = str(documents[-1].id) if documents else None
        selective_reindex = build_knowledge_lifecycle(
            db,
            operation="reindex",
            mode="DOCUMENT",
            document_id=selected_document_id,
        )
        full_reindex = build_knowledge_lifecycle(db, operation="reindex", mode="FULL")
        documents = repository.list_documents(artifact_id=artifact_id, include_inactive=True)
        stale_target = documents[0] if documents else None
        if stale_target is not None:
            stale_target.status = "stale"
            db.add(stale_target)
            for chunk in repository.list_chunks_for_document(stale_target.id):
                chunk.status = "stale"
                db.add(chunk)
            db.commit()
        stale_cleanup = build_knowledge_lifecycle(db, operation="cleanup", mode="ARTIFACT", artifact_id=artifact_id)
        remaining_documents = repository.list_documents(artifact_id=artifact_id, include_inactive=False)
        if remaining_documents:
            source_chunks = repository.list_chunks_for_document(remaining_documents[-1].id)
            if source_chunks:
                source = source_chunks[0]
                duplicate = KnowledgeChunk(
                    knowledge_document_id=source.knowledge_document_id,
                    published_chunk_id=f"published-chunk:duplicate:{uuid.uuid4()}",
                    publication_id=source.publication_id,
                    artifact_id=source.artifact_id,
                    chunk_index=max(chunk.chunk_index for chunk in source_chunks) + 100,
                    text=source.text,
                    content_hash=source.content_hash,
                    semantic_hash=source.semantic_hash,
                    content_type=source.content_type,
                    chunk_scope=source.chunk_scope,
                    status="indexed",
                    metadata_json=dict(source.metadata_json or {}),
                )
                db.add(duplicate)
                db.commit()
        duplicate_cleanup = build_knowledge_lifecycle(db, operation="cleanup", mode="FULL")
        health = build_knowledge_index_health(db)
        statistics = build_knowledge_index_statistics(db)
        search = build_enterprise_search(db=db, query=QUERY, top_k=5)
        lifecycle_run_id = duplicate_cleanup.get("lifecycle_run", {}).get("knowledge_lifecycle_run_id")
        persistence_execution_id = f"knowledge-lifecycle:cleanup:FULL:{lifecycle_run_id}"
        persistence_readback = read_runtime_persistence(db, execution_id=persistence_execution_id)
    finally:
        db.close()

    processing_result = processing.get("processing_result") if isinstance(processing.get("processing_result"), dict) else {}
    initial_ok = all(
        (
            verify_result.get("storage_verified") is True,
            processing_result.get("processing_completed") is True,
            initial_publication.get("publication_completed") is True,
            initial.get("lifecycle_completed") is True,
            initial.get("decision") in {"update", "rebuild"},
            initial.get("index_result", {}).get("index_completed") is True,
        )
    )
    incremental_ok = all(
        (
            incremental_ignore.get("lifecycle_completed") is True,
            incremental_ignore.get("decision") == "ignore",
        )
    )
    publication_update_ok = all(
        (
            publication_update.get("lifecycle_completed") is True,
            publication_update.get("decision") in {"update", "rebuild"},
            publication_update.get("index_result", {}).get("index_completed") is True,
        )
    )
    selective_reindex_ok = all(
        (
            selective_reindex.get("lifecycle_completed") is True,
            selective_reindex.get("mode") == "DOCUMENT",
            selective_reindex.get("decision") in {"ignore", "rebuild"},
        )
    )
    full_reindex_ok = all(
        (
            full_reindex.get("lifecycle_completed") is True,
            full_reindex.get("mode") == "FULL",
        )
    )
    cleanup_ok = all(
        (
            stale_cleanup.get("lifecycle_completed") is True,
            int(stale_cleanup.get("stale_documents_removed") or 0) >= 1,
            duplicate_cleanup.get("lifecycle_completed") is True,
            int(duplicate_cleanup.get("duplicates_removed") or 0) >= 1,
        )
    )
    persistence_ok = all(
        (
            persistence_readback.get("persistence_status") == "persisted",
            len(_records(persistence_readback, "knowledge_lifecycle", "lifecycle_result")) == 1,
            len(_records(persistence_readback, "knowledge_lifecycle", "index_health")) == 1,
        )
    )
    search_ok = all(
        (
            search.get("search_completed") is True,
            search.get("search_succeeded") is True,
            int(search.get("result_count") or 0) >= 1,
            search.get("semantic_search_used") is False,
            search.get("embeddings_required") is False,
            search.get("ai_required") is False,
        )
    )
    health_ok = all(
        (
            int(health.get("health", {}).get("indexed_documents") or 0) >= 1,
            int(health.get("health", {}).get("indexed_chunks") or 0) >= 1,
            "pending_reindex" in health.get("health", {}),
        )
    )
    statistics_ok = all(
        (
            int(statistics.get("statistics", {}).get("indexed_bytes") or 0) > 0,
            "average_chunks_per_document" in statistics.get("statistics", {}),
            "rebuild_required" in statistics.get("statistics", {}),
        )
    )

    _expect(initial_ok, failures, "initial indexing must persist a knowledge document")
    _expect(incremental_ok, failures, "incremental indexing must ignore unchanged publications")
    _expect(publication_update_ok, failures, "publication update must update or rebuild the index")
    _expect(selective_reindex_ok, failures, "DOCUMENT selective reindex must execute")
    _expect(full_reindex_ok, failures, "FULL reindex must execute")
    _expect(cleanup_ok, failures, "stale and duplicate cleanup must execute deterministically")
    _expect(persistence_ok, failures, "knowledge lifecycle runtime persistence must be readable")
    _expect(search_ok, failures, "enterprise search must remain consistent after lifecycle operations")
    _expect(health_ok, failures, "health metrics must be persisted and populated")
    _expect(statistics_ok, failures, "statistics must be persisted and populated")

    payload = {
        "passed": all(
            (
                initial_ok,
                incremental_ok,
                publication_update_ok,
                selective_reindex_ok,
                full_reindex_ok,
                cleanup_ok,
                persistence_ok,
                search_ok,
                health_ok,
                statistics_ok,
            )
        )
        and not failures,
        "initial_indexing": bool(initial_ok),
        "incremental_update": bool(incremental_ok),
        "publication_update": bool(publication_update_ok),
        "selective_reindex": bool(selective_reindex_ok),
        "full_reindex": bool(full_reindex_ok),
        "stale_cleanup": int(stale_cleanup.get("stale_documents_removed") or 0),
        "orphan_cleanup": int(stale_cleanup.get("orphan_chunks_removed") or 0),
        "duplicate_cleanup": int(duplicate_cleanup.get("duplicates_removed") or 0),
        "runtime_persistence": bool(persistence_ok),
        "enterprise_search_consistency": bool(search_ok),
        "health_metrics": health.get("health"),
        "statistics": statistics.get("statistics"),
        "semantic_search_used": bool(search.get("semantic_search_used")),
        "embeddings_required": bool(search.get("embeddings_required")),
        "ai_required": bool(search.get("ai_required")),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
