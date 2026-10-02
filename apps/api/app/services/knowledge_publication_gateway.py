"""Knowledge publication gateway from Chunk Result to publication runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.knowledge_publication_session import (
    build_knowledge_publication_session,
    serialize_knowledge_publication_session,
)

KNOWLEDGE_PUBLICATION_GATEWAY_SCHEMA_VERSION = "1"
KNOWLEDGE_PUBLICATION_GATEWAY_STATUS_BLOCKED = "blocked"
KNOWLEDGE_PUBLICATION_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class KnowledgePublicationGateway:
    artifact_id: str | None
    processing_session_id: str | None
    chunk_session_id: str | None
    publication_session: dict[str, Any]
    gateway_status: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def build_knowledge_publication_gateway(
    chunk_result: dict[str, Any],
    *,
    publication_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    publication_session = serialize_knowledge_publication_session(
        build_knowledge_publication_session(chunk_result, publication_config=publication_config)
    )
    ready = bool(publication_session.get("publication_session_ready"))
    gateway = KnowledgePublicationGateway(
        artifact_id=chunk_result.get("artifact_id"),
        processing_session_id=chunk_result.get("processing_session_id"),
        chunk_session_id=chunk_result.get("chunk_session_id"),
        publication_session=publication_session,
        gateway_status=KNOWLEDGE_PUBLICATION_GATEWAY_STATUS_READY
        if ready
        else KNOWLEDGE_PUBLICATION_GATEWAY_STATUS_BLOCKED,
        blocking_issues=publication_session.get("blocking_issues") or [],
        warnings=publication_session.get("warnings") or [],
        next_available_actions=[
            {
                "action": "execute_knowledge_publication",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "publication_session_not_ready",
                "embeddings_created": False,
                "semantic_index_created": False,
                "ai_required": False,
            }
        ],
    )
    serialized = {
        "knowledge_publication_gateway_schema_version": KNOWLEDGE_PUBLICATION_GATEWAY_SCHEMA_VERSION,
        "artifact_id": gateway.artifact_id,
        "processing_session_id": gateway.processing_session_id,
        "chunk_session_id": gateway.chunk_session_id,
        "publication_gateway_ready": gateway.gateway_status == KNOWLEDGE_PUBLICATION_GATEWAY_STATUS_READY,
        "gateway_status": gateway.gateway_status,
        "publication_session": dict(gateway.publication_session),
        "blocking_issues": list(gateway.blocking_issues),
        "warnings": list(gateway.warnings),
        "next_available_actions": list(gateway.next_available_actions),
        "knowledge_published": False,
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**serialized, "publication_gateway": serialized}
