"""Embedding Runtime gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.embedding_session import build_embedding_session, issue, serialize_embedding_session, sort_issues

EMBEDDING_GATEWAY_SCHEMA_VERSION = "1"


def build_embedding_gateway(
    db: Session,
    *,
    chunk_id: str | None,
    model_name: str | None = None,
    model_version: str | None = None,
    embedding_dimensions: int | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = serialize_embedding_session(
        build_embedding_session(
            chunk_id=chunk_id,
            model_name=model_name,
            model_version=model_version,
            embedding_dimensions=embedding_dimensions,
            runtime_metadata=runtime_metadata,
        )
    )
    blocking_issues = list(session.get("blocking_issues") or [])
    warnings = list(session.get("warnings") or [])
    chunk = None
    if chunk_id:
        try:
            chunk = KnowledgeIndexRepository(db).get_chunk(uuid.UUID(str(chunk_id)))
        except (TypeError, ValueError):
            blocking_issues.append(
                issue(
                    "chunk_id_invalid",
                    "Embedding runtime requires a valid knowledge chunk id.",
                    component="embedding_gateway",
                    item_id=str(chunk_id),
                )
            )
    if chunk_id and chunk is None and not any(item.get("code") == "chunk_id_invalid" for item in blocking_issues):
        blocking_issues.append(
            issue(
                "knowledge_chunk_missing",
                "Embedding runtime requires an existing knowledge chunk.",
                component="knowledge_index",
                item_id=str(chunk_id),
            )
        )
    if chunk is not None and chunk.status != "indexed":
        blocking_issues.append(
            issue(
                "knowledge_chunk_not_indexed",
                "Embedding runtime requires an indexed knowledge chunk.",
                component="knowledge_index",
                item_id=str(chunk.id),
            )
        )
    if chunk is not None and not chunk.knowledge_document_id:
        blocking_issues.append(
            issue(
                "knowledge_document_missing",
                "Embedding runtime requires a chunk linked to a knowledge document.",
                component="knowledge_index",
                item_id=str(chunk.id),
            )
        )
    warnings.append(
        issue(
            "embedding_provider_not_configured",
            "Embedding provider configuration is intentionally not required in this metadata-only foundation.",
            component="embedding_gateway",
            severity="warning",
        )
    )
    ready = bool(session.get("embedding_session_ready")) and not blocking_issues
    return {
        "embedding_gateway_schema_version": EMBEDDING_GATEWAY_SCHEMA_VERSION,
        "embedding_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "embedding_session": session,
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
        "future_provider_configuration_required": False,
        "embedding_vector_generated": False,
        "embedding_provider_called": False,
        "semantic_search_used": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "next_available_actions": [
            {
                "action": "persist_embedding_record",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "embedding_gateway_blocked",
            }
        ],
        "persistence_status": "not_persisted",
    }
