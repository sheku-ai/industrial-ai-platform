"""Knowledge Index session foundation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

KNOWLEDGE_INDEX_SESSION_SCHEMA_VERSION = "1"
KNOWLEDGE_INDEX_STATE_BLOCKED = "blocked"
KNOWLEDGE_INDEX_STATE_READY = "ready"
KNOWLEDGE_INDEX_RUNTIME_VERSION = "knowledge_index_runtime/1.0"


@dataclass(frozen=True)
class KnowledgeIndexSession:
    index_session_id: str | None
    artifact_id: str | None
    publication_id: str | None
    published_chunk_count: int
    index_state: str
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


def _stable_session_id(artifact_id: str | None, publication_id: str | None) -> str | None:
    if not artifact_id and not publication_id:
        return None
    digest = hashlib.sha256(
        f"{artifact_id or 'artifact:unknown'}|{publication_id or 'publication:unknown'}".encode()
    ).hexdigest()[:24]
    return f"knowledge-index-session:{digest}"


def build_knowledge_index_session(publication_result: dict[str, Any]) -> KnowledgeIndexSession:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    chunks = (
        publication_result.get("published_chunks")
        if isinstance(publication_result.get("published_chunks"), list)
        else []
    )
    artifact_id = publication_result.get("artifact_id") or (
        chunks[0].get("artifact_id") if chunks and isinstance(chunks[0], dict) else None
    )
    publication_id = publication_result.get("publication_id") or (
        chunks[0].get("publication_id") if chunks and isinstance(chunks[0], dict) else None
    )
    if publication_result.get("publication_completed") is not True:
        blocking_issues.append(
            issue(
                "publication_not_completed",
                "Knowledge indexing requires publication_completed=true.",
                component="knowledge_index",
            )
        )
    if publication_result.get("knowledge_published") is not True:
        blocking_issues.append(
            issue(
                "knowledge_not_published",
                "Knowledge indexing requires knowledge_published=true.",
                component="knowledge_index",
            )
        )
    if not artifact_id:
        blocking_issues.append(
            issue("artifact_id_missing", "Knowledge indexing requires artifact_id.", component="knowledge_index")
        )
    if not publication_id:
        blocking_issues.append(
            issue("publication_id_missing", "Knowledge indexing requires publication_id.", component="knowledge_index")
        )
    if not chunks:
        blocking_issues.append(
            issue(
                "published_chunks_missing", "Knowledge indexing requires published chunks.", component="knowledge_index"
            )
        )
    for position, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            blocking_issues.append(
                issue(
                    "published_chunk_invalid",
                    "Published chunk must be an object.",
                    component="knowledge_index",
                    item_id=str(position),
                )
            )
            continue
        if not chunk.get("published_chunk_id") or not chunk.get("content_hash") or not chunk.get("text"):
            blocking_issues.append(
                issue(
                    "published_chunk_incomplete",
                    "Published chunk requires id, hash and text.",
                    component="knowledge_index",
                    item_id=str(position),
                )
            )
    ready = not blocking_issues
    return KnowledgeIndexSession(
        index_session_id=_stable_session_id(
            str(artifact_id) if artifact_id else None, str(publication_id) if publication_id else None
        ),
        artifact_id=str(artifact_id) if artifact_id else None,
        publication_id=str(publication_id) if publication_id else None,
        published_chunk_count=len(chunks),
        index_state=KNOWLEDGE_INDEX_STATE_READY if ready else KNOWLEDGE_INDEX_STATE_BLOCKED,
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {"action": "index_published_knowledge", "available": ready, "status": "ready" if ready else "blocked"}
        ],
    )


def serialize_knowledge_index_session(session: KnowledgeIndexSession) -> dict[str, Any]:
    return {
        "knowledge_index_session_schema_version": KNOWLEDGE_INDEX_SESSION_SCHEMA_VERSION,
        "index_session_id": session.index_session_id,
        "artifact_id": session.artifact_id,
        "publication_id": session.publication_id,
        "published_chunk_count": session.published_chunk_count,
        "index_state": session.index_state,
        "index_session_ready": session.index_state == KNOWLEDGE_INDEX_STATE_READY,
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "persistence_status": "not_persisted",
    }
