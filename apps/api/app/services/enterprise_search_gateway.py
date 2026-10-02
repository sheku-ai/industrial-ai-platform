"""Enterprise search gateway for the PostgreSQL knowledge repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.enterprise_search_session import build_enterprise_search_session, serialize_enterprise_search_session

ENTERPRISE_SEARCH_GATEWAY_SCHEMA_VERSION = "1"
ENTERPRISE_SEARCH_GATEWAY_STATUS_BLOCKED = "blocked"
ENTERPRISE_SEARCH_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class EnterpriseSearchGateway:
    search_session: dict[str, Any]
    gateway_status: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def build_enterprise_search_gateway(
    *,
    query: str,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
    indexed_chunk_count: int = 0,
) -> dict[str, Any]:
    search_session = serialize_enterprise_search_session(
        build_enterprise_search_session(
            query=query, top_k=top_k, search_config=search_config, indexed_chunk_count=indexed_chunk_count
        )
    )
    ready = bool(search_session.get("search_session_ready"))
    gateway = EnterpriseSearchGateway(
        search_session=search_session,
        gateway_status=ENTERPRISE_SEARCH_GATEWAY_STATUS_READY if ready else ENTERPRISE_SEARCH_GATEWAY_STATUS_BLOCKED,
        blocking_issues=search_session.get("blocking_issues") or [],
        warnings=search_session.get("warnings") or [],
        next_available_actions=[
            {
                "action": "execute_enterprise_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "search_session_not_ready",
                "semantic_search_used": False,
                "embeddings_required": False,
                "ai_required": False,
            }
        ],
    )
    serialized = {
        "enterprise_search_gateway_schema_version": ENTERPRISE_SEARCH_GATEWAY_SCHEMA_VERSION,
        "search_gateway_ready": gateway.gateway_status == ENTERPRISE_SEARCH_GATEWAY_STATUS_READY,
        "gateway_status": gateway.gateway_status,
        "search_session": dict(gateway.search_session),
        "blocking_issues": list(gateway.blocking_issues),
        "warnings": list(gateway.warnings),
        "next_available_actions": list(gateway.next_available_actions),
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**serialized, "search_gateway": serialized}
