"""Vector Index session foundation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

VECTOR_INDEX_SESSION_SCHEMA_VERSION = "1"
VECTOR_INDEX_RUNTIME_VERSION = "vector_index_runtime/1.0"
VECTOR_INDEX_STATE_BLOCKED = "blocked"
VECTOR_INDEX_STATE_READY = "ready"
DEFAULT_VECTOR_INDEX_NAME = "derived-vector-index"
DEFAULT_VECTOR_INDEX_PROVIDER = "qdrant-disabled"
DEFAULT_VECTOR_INDEX_PROVIDER_TYPE = "descriptor-only"
DEFAULT_VECTOR_INDEX_VERSION = "descriptor-only/1.0"


@dataclass(frozen=True)
class VectorIndexSession:
    vector_index_session_id: str | None
    embedding_id: str | None
    index_name: str
    index_provider: str
    index_provider_type: str
    index_version: str
    qdrant_provider_name: str
    qdrant_collection_name: str
    vector_dimensions: int
    vector_index_state: str
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
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


def _stable_session_id(
    *, embedding_id: str | None, index_name: str, index_provider: str, index_version: str
) -> str | None:
    if not embedding_id:
        return None
    digest = hashlib.sha256(f"{embedding_id}|{index_name}|{index_provider}|{index_version}".encode()).hexdigest()[:24]
    return f"vector-index-session:{digest}"


def build_vector_index_session(
    *,
    embedding_id: str | None,
    index_name: str | None = None,
    index_provider: str | None = None,
    index_provider_type: str | None = None,
    index_version: str | None = None,
    qdrant_provider_name: str | None = None,
    qdrant_collection_name: str | None = None,
    vector_dimensions: int | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> VectorIndexSession:
    resolved_index_name = (index_name or DEFAULT_VECTOR_INDEX_NAME).strip() or DEFAULT_VECTOR_INDEX_NAME
    resolved_provider = (index_provider or DEFAULT_VECTOR_INDEX_PROVIDER).strip() or DEFAULT_VECTOR_INDEX_PROVIDER
    resolved_provider_type = (
        index_provider_type or DEFAULT_VECTOR_INDEX_PROVIDER_TYPE
    ).strip() or DEFAULT_VECTOR_INDEX_PROVIDER_TYPE
    resolved_version = (index_version or DEFAULT_VECTOR_INDEX_VERSION).strip() or DEFAULT_VECTOR_INDEX_VERSION
    resolved_qdrant_provider_name = (qdrant_provider_name or resolved_provider).strip() or DEFAULT_VECTOR_INDEX_PROVIDER
    resolved_qdrant_collection_name = (qdrant_collection_name or resolved_index_name).strip() or resolved_index_name
    resolved_dimensions = int(vector_dimensions or 0)
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not embedding_id:
        blocking_issues.append(
            issue(
                "embedding_id_missing",
                "Vector index preparation requires an embedding record id.",
                component="vector_index_session",
            )
        )
    if resolved_dimensions < 0:
        blocking_issues.append(
            issue(
                "vector_dimensions_invalid",
                "Vector dimensions must be greater than or equal to zero.",
                component="vector_index_session",
            )
        )
    if resolved_provider_type not in {"descriptor-only", "disabled"}:
        blocking_issues.append(
            issue(
                "vector_provider_execution_blocked",
                "Vector index foundation only allows descriptor-only or disabled providers.",
                component="vector_index_session",
                item_id=resolved_provider,
            )
        )
    warnings.append(
        issue(
            "qdrant_execution_disabled",
            "Qdrant is descriptor-only and non-authoritative in this foundation.",
            component="vector_index_session",
            severity="warning",
        )
    )
    ready = not blocking_issues
    return VectorIndexSession(
        vector_index_session_id=_stable_session_id(
            embedding_id=embedding_id,
            index_name=resolved_index_name,
            index_provider=resolved_provider,
            index_version=resolved_version,
        ),
        embedding_id=embedding_id,
        index_name=resolved_index_name,
        index_provider=resolved_provider,
        index_provider_type=resolved_provider_type,
        index_version=resolved_version,
        qdrant_provider_name=resolved_qdrant_provider_name,
        qdrant_collection_name=resolved_qdrant_collection_name,
        vector_dimensions=resolved_dimensions,
        vector_index_state=VECTOR_INDEX_STATE_READY if ready else VECTOR_INDEX_STATE_BLOCKED,
        runtime_metadata={
            "vector_index_runtime_version": VECTOR_INDEX_RUNTIME_VERSION,
            "derived_from_postgresql": True,
            "descriptor_only": True,
            "qdrant_authoritative": False,
            "qdrant_provider_name": resolved_qdrant_provider_name,
            "qdrant_collection_name": resolved_qdrant_collection_name,
            "postgresql_source_of_truth": True,
            **dict(runtime_metadata or {}),
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "prepare_vector_index_metadata",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "vector_index_session_blocked",
            }
        ],
    )


def serialize_vector_index_session(session: VectorIndexSession) -> dict[str, Any]:
    return {
        "vector_index_session_schema_version": VECTOR_INDEX_SESSION_SCHEMA_VERSION,
        "vector_index_session_id": session.vector_index_session_id,
        "embedding_id": session.embedding_id,
        "index_name": session.index_name,
        "index_provider": session.index_provider,
        "index_provider_type": session.index_provider_type,
        "index_version": session.index_version,
        "qdrant_provider_name": session.qdrant_provider_name,
        "qdrant_collection_name": session.qdrant_collection_name,
        "vector_dimensions": session.vector_dimensions,
        "vector_index_state": session.vector_index_state,
        "vector_index_session_ready": session.vector_index_state == VECTOR_INDEX_STATE_READY,
        "runtime_metadata": dict(session.runtime_metadata),
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "vector_values_stored": False,
        "qdrant_called": False,
        "network_call_attempted": False,
        "semantic_search_enabled": False,
        "hybrid_search_enabled": False,
        "postgresql_source_of_truth": True,
        "persistence_status": "not_persisted",
    }
