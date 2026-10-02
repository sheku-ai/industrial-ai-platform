"""Vector Index gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.vector_index import VectorIndexRepository
from app.services.qdrant_provider_registry import get_qdrant_provider_registry
from app.services.qdrant_provider_runtime import get_qdrant_provider_runtime_adapter
from app.services.vector_index_session import (
    build_vector_index_session,
    issue,
    serialize_vector_index_session,
    sort_issues,
)

VECTOR_INDEX_GATEWAY_SCHEMA_VERSION = "1"


def build_vector_index_gateway(
    db: Session,
    *,
    embedding_id: str | None,
    index_name: str | None = None,
    index_provider: str | None = None,
    index_provider_type: str | None = None,
    index_version: str | None = None,
    qdrant_provider_name: str | None = None,
    qdrant_collection_name: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = VectorIndexRepository(db)
    embedding = None
    chunk = None
    embedding_uuid = None
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if embedding_id:
        try:
            embedding_uuid = uuid.UUID(str(embedding_id))
            embedding = repository.get_embedding(embedding_uuid)
        except (TypeError, ValueError):
            blocking_issues.append(
                issue(
                    "embedding_id_invalid",
                    "Vector index preparation requires a valid embedding id.",
                    component="vector_index_gateway",
                    item_id=str(embedding_id),
                )
            )
    if (
        embedding_id
        and embedding is None
        and not any(item.get("code") == "embedding_id_invalid" for item in blocking_issues)
    ):
        blocking_issues.append(
            issue(
                "embedding_record_missing",
                "Vector index preparation requires an existing embedding record.",
                component="embedding_runtime",
                item_id=str(embedding_id),
            )
        )
    if embedding is not None and embedding.embedding_status not in {"completed"}:
        blocking_issues.append(
            issue(
                "embedding_status_incompatible",
                "Vector index preparation requires a completed embedding metadata record.",
                component="embedding_runtime",
                item_id=embedding.embedding_status,
            )
        )
    if embedding is not None:
        chunk = repository.get_chunk(embedding.chunk_id)
    if embedding is not None and chunk is None:
        blocking_issues.append(
            issue(
                "knowledge_chunk_missing",
                "Vector index preparation requires the source knowledge chunk.",
                component="knowledge_index",
                item_id=str(embedding.chunk_id),
            )
        )
    vector_dimensions = int(embedding.embedding_dimensions if embedding is not None else 0)
    session = serialize_vector_index_session(
        build_vector_index_session(
            embedding_id=str(embedding_uuid) if embedding_uuid else embedding_id,
            index_name=index_name,
            index_provider=index_provider,
            index_provider_type=index_provider_type,
            index_version=index_version,
            qdrant_provider_name=qdrant_provider_name,
            qdrant_collection_name=qdrant_collection_name,
            vector_dimensions=vector_dimensions,
            runtime_metadata=runtime_metadata,
        )
    )
    qdrant_provider, qdrant_resolution = get_qdrant_provider_registry().resolve(
        qdrant_provider_name or session.get("qdrant_provider_name")
    )
    qdrant_adapter = get_qdrant_provider_runtime_adapter()
    qdrant_plan = qdrant_adapter.build_execution_plan(
        qdrant_provider,
        collection_name=qdrant_collection_name or session.get("qdrant_collection_name"),
        vector_dimensions=vector_dimensions,
    )
    qdrant_health = qdrant_adapter.evaluate_health(qdrant_provider)
    blocking_issues.extend(session.get("blocking_issues") or [])
    warnings.extend(session.get("warnings") or [])
    ready = bool(session.get("vector_index_session_ready")) and not blocking_issues
    return {
        "vector_index_gateway_schema_version": VECTOR_INDEX_GATEWAY_SCHEMA_VERSION,
        "vector_index_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "vector_index_session": session,
        "embedding_record": {
            "embedding_id": str(embedding.embedding_id),
            "chunk_id": str(embedding.chunk_id),
            "model_name": embedding.model_name,
            "model_version": embedding.model_version,
            "embedding_dimensions": embedding.embedding_dimensions,
            "embedding_status": embedding.embedding_status,
            "embedding_hash": embedding.embedding_hash,
            "runtime_metadata": embedding.runtime_metadata or {},
        }
        if embedding is not None
        else None,
        "knowledge_chunk": {
            "knowledge_chunk_id": str(chunk.id),
            "knowledge_document_id": str(chunk.knowledge_document_id),
            "artifact_id": chunk.artifact_id,
            "publication_id": chunk.publication_id,
            "published_chunk_id": chunk.published_chunk_id,
            "chunk_index": chunk.chunk_index,
            "status": chunk.status,
            "content_hash": chunk.content_hash,
            "semantic_hash": chunk.semantic_hash,
        }
        if chunk is not None
        else None,
        "source_of_truth": "postgresql",
        "derived_from_embedding_record": embedding is not None,
        "vector_values_stored": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "qdrant_provider": qdrant_provider.as_dict(),
        "qdrant_provider_resolution": qdrant_resolution,
        "qdrant_execution_plan": qdrant_plan.as_dict(),
        "qdrant_health": qdrant_health.as_dict(),
        "qdrant_enabled": qdrant_provider.enabled,
        "qdrant_descriptor_only": qdrant_provider.descriptor_only,
        "semantic_search_enabled": False,
        "hybrid_search_enabled": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "persist_vector_index_record",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "vector_index_gateway_blocked",
            }
        ],
        "persistence_status": "not_persisted",
    }


def build_vector_index_health(db: Session) -> dict[str, Any]:
    repository = VectorIndexRepository(db)
    pending = repository.list_pending_vector_index_records(limit=500)
    records = repository.list_vector_index_records(limit=500)
    return {
        "vector_index_health_schema_version": "1",
        "vector_index_runtime_available": True,
        "vector_index_records": len(records),
        "pending_vector_index_records": len(pending),
        "vector_values_stored": False,
        "qdrant_called": False,
        "semantic_search_enabled": False,
        "hybrid_search_enabled": False,
        "postgresql_source_of_truth": True,
        "persistence_status": "available",
    }
