"""Enterprise search session foundation for indexed PostgreSQL knowledge chunks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

ENTERPRISE_SEARCH_SESSION_SCHEMA_VERSION = "1"
ENTERPRISE_SEARCH_STATE_BLOCKED = "blocked"
ENTERPRISE_SEARCH_STATE_READY = "ready"
ENTERPRISE_SEARCH_MODE_LEXICAL = "lexical"
ENTERPRISE_SEARCH_SCOPE_MEMORY = "postgres_knowledge_repository"
DEFAULT_TOP_K = 5
MAX_TOP_K = 100
MAX_QUERY_CHARS = 512


@dataclass(frozen=True)
class EnterpriseSearchSession:
    search_session_id: str | None
    query: str
    normalized_query: str
    top_k: int
    search_mode: str
    search_scope: str
    search_state: str
    search_config: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def issue(
    code: str,
    message: str,
    *,
    component: str,
    severity: str = "blocking",
    item_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def normalize_query_text(query: Any) -> str:
    text = "" if query is None else str(query)
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _canonical_session_context(search_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(search_config or {})
    filters = config.get("filters") if isinstance(config.get("filters"), dict) else {}
    canonical_filters = {
        str(key): value for key, value in sorted(filters.items(), key=lambda item: str(item[0])) if value is not None
    }
    return {
        "filters": canonical_filters,
        "include_facets": bool(config.get("include_facets", False)),
        "include_debug": bool(config.get("include_debug", False)),
    }


def _stable_search_session_id(
    *,
    normalized_query: str,
    top_k: int,
    search_config: dict[str, Any] | None,
) -> str | None:
    if not normalized_query:
        return None
    identity = {
        "normalized_query": normalized_query,
        "top_k": int(top_k),
        "search_scope": ENTERPRISE_SEARCH_SCOPE_MEMORY,
        **_canonical_session_context(search_config),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"enterprise-search-session:{digest}"


def default_search_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(overrides or {})
    top_k = values.get("top_k", DEFAULT_TOP_K)
    top_k_capped = False
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = DEFAULT_TOP_K
    if top_k > MAX_TOP_K:
        top_k_capped = True
    return {
        "top_k": max(1, min(top_k, MAX_TOP_K)),
        "top_k_capped": top_k_capped,
        "max_query_chars": int(values.get("max_query_chars") or MAX_QUERY_CHARS),
        "search_mode": ENTERPRISE_SEARCH_MODE_LEXICAL,
        "search_scope": ENTERPRISE_SEARCH_SCOPE_MEMORY,
        "semantic_search_enabled": False,
        "embeddings_required": False,
        "ai_required": False,
        "deterministic_ranking": True,
    }


def validate_search_session_readiness(
    *,
    query: str,
    normalized_query: str,
    search_config: dict[str, Any],
    indexed_chunk_count: int,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    max_query_chars = int(search_config.get("max_query_chars") or MAX_QUERY_CHARS)

    if not normalized_query:
        blocking_issues.append(
            issue("query_empty", "Enterprise search requires a non-empty query.", component="enterprise_search")
        )
    if len(query) > max_query_chars:
        blocking_issues.append(
            issue("query_too_large", "Enterprise search query exceeds max_query_chars.", component="enterprise_search")
        )
    if search_config.get("search_mode") != ENTERPRISE_SEARCH_MODE_LEXICAL:
        blocking_issues.append(
            issue(
                "search_mode_not_supported",
                "Enterprise search foundation supports only lexical mode.",
                component="enterprise_search",
            )
        )
    if search_config.get("search_scope") != ENTERPRISE_SEARCH_SCOPE_MEMORY:
        blocking_issues.append(
            issue(
                "search_scope_not_supported",
                "Enterprise search foundation supports only the PostgreSQL knowledge repository.",
                component="enterprise_search",
            )
        )
    if indexed_chunk_count < 1:
        blocking_issues.append(
            issue(
                "knowledge_chunks_missing",
                "Enterprise search requires indexed knowledge chunks in PostgreSQL.",
                component="knowledge_repository",
            )
        )
    if search_config.get("top_k_capped"):
        warnings.append(
            issue(
                "top_k_capped",
                "Enterprise search top_k was capped to the maximum allowed value.",
                component="enterprise_search",
                severity="warning",
            )
        )

    return {
        "validation_status": ENTERPRISE_SEARCH_STATE_BLOCKED if blocking_issues else ENTERPRISE_SEARCH_STATE_READY,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
    }


def build_enterprise_search_session(
    *,
    query: str,
    top_k: int | None = None,
    search_config: dict[str, Any] | None = None,
    indexed_chunk_count: int = 0,
) -> EnterpriseSearchSession:
    config_overrides = dict(search_config or {})
    if top_k is not None:
        config_overrides["top_k"] = top_k
    config = default_search_config(config_overrides)
    config["indexed_chunk_count"] = indexed_chunk_count
    normalized_query = normalize_query_text(query)
    validation = validate_search_session_readiness(
        query=query,
        normalized_query=normalized_query,
        search_config=config,
        indexed_chunk_count=indexed_chunk_count,
    )
    ready = not validation["blocking_issues"]
    return EnterpriseSearchSession(
        search_session_id=_stable_search_session_id(
            normalized_query=normalized_query,
            top_k=int(config["top_k"]),
            search_config=config_overrides,
        ),
        query=query,
        normalized_query=normalized_query,
        top_k=int(config["top_k"]),
        search_mode=ENTERPRISE_SEARCH_MODE_LEXICAL,
        search_scope=ENTERPRISE_SEARCH_SCOPE_MEMORY,
        search_state=ENTERPRISE_SEARCH_STATE_READY if ready else ENTERPRISE_SEARCH_STATE_BLOCKED,
        search_config=config,
        blocking_issues=validation["blocking_issues"],
        warnings=validation["warnings"],
        next_available_actions=[
            {
                "action": "execute_enterprise_search",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "search_session_validation_blocked",
                "semantic_search_used": False,
                "embeddings_required": False,
                "ai_required": False,
            }
        ],
    )


def serialize_enterprise_search_session(session: EnterpriseSearchSession) -> dict[str, Any]:
    return {
        "enterprise_search_session_schema_version": ENTERPRISE_SEARCH_SESSION_SCHEMA_VERSION,
        "search_session_id": session.search_session_id,
        "query": session.query,
        "normalized_query": session.normalized_query,
        "top_k": session.top_k,
        "search_mode": session.search_mode,
        "search_scope": session.search_scope,
        "search_state": session.search_state,
        "search_session_ready": session.search_state == ENTERPRISE_SEARCH_STATE_READY,
        "search_config": dict(session.search_config),
        "indexed_chunk_count": session.search_config.get("indexed_chunk_count"),
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "semantic_search_enabled": False,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
