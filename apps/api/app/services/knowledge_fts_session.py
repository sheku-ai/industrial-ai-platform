"""Knowledge PostgreSQL FTS session foundation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

KNOWLEDGE_FTS_SESSION_SCHEMA_VERSION = "1"
KNOWLEDGE_FTS_RUNTIME_VERSION = "knowledge_fts_runtime/1.0"
KNOWLEDGE_FTS_STATE_BLOCKED = "blocked"
KNOWLEDGE_FTS_STATE_READY = "ready"
DEFAULT_TOP_K = 5
MAX_TOP_K = 100
MAX_QUERY_CHARS = 512


@dataclass(frozen=True)
class KnowledgeFtsSession:
    fts_session_id: str | None
    query: str
    normalized_query: str
    top_k: int
    offset: int
    limit: int
    filters: dict[str, Any]
    fts_state: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def issue(
    code: str, message: str, *, component: str, severity: str = "blocking", item_id: str | None = None
) -> dict[str, Any]:
    return {"code": code, "severity": severity, "component": component, "item_id": item_id, "message": message}


def sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def normalize_fts_query(query: Any) -> str:
    text = "" if query is None else str(query)
    text = text.replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def _stable_session_id(*, normalized_query: str, top_k: int, filters: dict[str, Any]) -> str | None:
    if not normalized_query:
        return None
    seed = f"{normalized_query}|{top_k}|{sorted(filters.items())}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"knowledge-fts-session:{digest}"


def build_knowledge_fts_session(
    *,
    query: str,
    top_k: int | None = None,
    offset: int = 0,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    indexed_chunk_count: int = 0,
) -> KnowledgeFtsSession:
    normalized_query = normalize_fts_query(query)
    requested_top_k = top_k if top_k is not None else DEFAULT_TOP_K
    try:
        bounded_top_k = max(1, min(int(requested_top_k), MAX_TOP_K))
    except (TypeError, ValueError):
        bounded_top_k = DEFAULT_TOP_K
    try:
        bounded_offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        bounded_offset = 0
    try:
        bounded_limit = max(1, min(int(limit if limit is not None else bounded_top_k), 50))
    except (TypeError, ValueError):
        bounded_limit = min(bounded_top_k, 50)
    clean_filters = {key: value for key, value in dict(filters or {}).items() if value not in (None, "")}
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not normalized_query:
        blocking_issues.append(
            issue("query_empty", "PostgreSQL FTS requires a non-empty query.", component="knowledge_fts")
        )
    if len(normalized_query) > MAX_QUERY_CHARS:
        blocking_issues.append(
            issue("query_too_large", "PostgreSQL FTS query exceeds max_query_chars.", component="knowledge_fts")
        )
    if indexed_chunk_count < 1:
        blocking_issues.append(
            issue(
                "indexed_chunks_missing", "PostgreSQL FTS requires indexed knowledge chunks.", component="knowledge_fts"
            )
        )
    if bounded_top_k != requested_top_k:
        warnings.append(
            issue(
                "top_k_normalized",
                "PostgreSQL FTS top_k was normalized.",
                component="knowledge_fts",
                severity="warning",
            )
        )
    ready = not blocking_issues
    return KnowledgeFtsSession(
        fts_session_id=_stable_session_id(
            normalized_query=normalized_query, top_k=bounded_top_k, filters=clean_filters
        ),
        query=query,
        normalized_query=normalized_query,
        top_k=bounded_top_k,
        offset=bounded_offset,
        limit=bounded_limit,
        filters=clean_filters,
        fts_state=KNOWLEDGE_FTS_STATE_READY if ready else KNOWLEDGE_FTS_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "execute_postgres_fts_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "knowledge_fts_session_blocked",
            }
        ],
    )


def serialize_knowledge_fts_session(session: KnowledgeFtsSession) -> dict[str, Any]:
    return {
        "knowledge_fts_session_schema_version": KNOWLEDGE_FTS_SESSION_SCHEMA_VERSION,
        "fts_session_id": session.fts_session_id,
        "query": session.query,
        "normalized_query": session.normalized_query,
        "top_k": session.top_k,
        "offset": session.offset,
        "limit": session.limit,
        "filters": dict(session.filters),
        "fts_state": session.fts_state,
        "fts_session_ready": session.fts_state == KNOWLEDGE_FTS_STATE_READY,
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "fts_config": "simple",
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": True,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
