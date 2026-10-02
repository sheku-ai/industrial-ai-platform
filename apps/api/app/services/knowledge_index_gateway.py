"""Knowledge Index gateway."""

from __future__ import annotations

from typing import Any

from app.services.knowledge_index_session import build_knowledge_index_session, serialize_knowledge_index_session

KNOWLEDGE_INDEX_GATEWAY_SCHEMA_VERSION = "1"


def build_knowledge_index_gateway(publication_result: dict[str, Any]) -> dict[str, Any]:
    session = serialize_knowledge_index_session(build_knowledge_index_session(publication_result))
    ready = bool(session.get("index_session_ready"))
    return {
        "knowledge_index_gateway_schema_version": KNOWLEDGE_INDEX_GATEWAY_SCHEMA_VERSION,
        "index_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "index_session": session,
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "execute_knowledge_index",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "knowledge_index_session_blocked",
            }
        ],
        "persistence_status": "not_persisted",
    }
