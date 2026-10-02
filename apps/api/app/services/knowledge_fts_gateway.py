"""Knowledge PostgreSQL FTS gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.knowledge_fts_session import build_knowledge_fts_session, serialize_knowledge_fts_session

KNOWLEDGE_FTS_GATEWAY_SCHEMA_VERSION = "1"
KNOWLEDGE_FTS_GATEWAY_STATUS_BLOCKED = "blocked"
KNOWLEDGE_FTS_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class KnowledgeFtsGateway:
    fts_session: dict[str, Any]
    gateway_status: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def build_knowledge_fts_gateway(
    *,
    query: str,
    top_k: int | None = None,
    offset: int = 0,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    indexed_chunk_count: int = 0,
) -> dict[str, Any]:
    fts_session = serialize_knowledge_fts_session(
        build_knowledge_fts_session(
            query=query,
            top_k=top_k,
            offset=offset,
            limit=limit,
            filters=filters,
            indexed_chunk_count=indexed_chunk_count,
        )
    )
    ready = bool(fts_session.get("fts_session_ready"))
    gateway = KnowledgeFtsGateway(
        fts_session=fts_session,
        gateway_status=KNOWLEDGE_FTS_GATEWAY_STATUS_READY if ready else KNOWLEDGE_FTS_GATEWAY_STATUS_BLOCKED,
        blocking_issues=fts_session.get("blocking_issues") or [],
        warnings=fts_session.get("warnings") or [],
        next_available_actions=[
            {
                "action": "execute_postgres_fts_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "knowledge_fts_gateway_blocked",
            }
        ],
    )
    serialized = {
        "knowledge_fts_gateway_schema_version": KNOWLEDGE_FTS_GATEWAY_SCHEMA_VERSION,
        "fts_gateway_ready": ready,
        "gateway_status": gateway.gateway_status,
        "fts_session": dict(gateway.fts_session),
        "blocking_issues": list(gateway.blocking_issues),
        "warnings": list(gateway.warnings),
        "next_available_actions": list(gateway.next_available_actions),
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": True,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**serialized, "knowledge_fts_gateway": serialized}
