"""Embedding Runtime session foundation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

EMBEDDING_SESSION_SCHEMA_VERSION = "1"
EMBEDDING_RUNTIME_VERSION = "embedding_runtime/1.0"
EMBEDDING_STATE_BLOCKED = "blocked"
EMBEDDING_STATE_READY = "ready"
DEFAULT_EMBEDDING_MODEL_NAME = "metadata-only"
DEFAULT_EMBEDDING_MODEL_VERSION = "metadata-only/1.0"
DEFAULT_EMBEDDING_DIMENSIONS = 0


@dataclass(frozen=True)
class EmbeddingSession:
    embedding_session_id: str | None
    chunk_id: str | None
    model_name: str
    model_version: str
    embedding_dimensions: int
    embedding_state: str
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


def _stable_session_id(*, chunk_id: str | None, model_name: str, model_version: str) -> str | None:
    if not chunk_id:
        return None
    digest = hashlib.sha256(f"{chunk_id}|{model_name}|{model_version}".encode()).hexdigest()[:24]
    return f"embedding-session:{digest}"


def build_embedding_session(
    *,
    chunk_id: str | None,
    model_name: str | None = None,
    model_version: str | None = None,
    embedding_dimensions: int | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> EmbeddingSession:
    resolved_model_name = (model_name or DEFAULT_EMBEDDING_MODEL_NAME).strip() or DEFAULT_EMBEDDING_MODEL_NAME
    resolved_model_version = (
        model_version or DEFAULT_EMBEDDING_MODEL_VERSION
    ).strip() or DEFAULT_EMBEDDING_MODEL_VERSION
    resolved_dimensions = int(
        embedding_dimensions if embedding_dimensions is not None else DEFAULT_EMBEDDING_DIMENSIONS
    )
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not chunk_id:
        blocking_issues.append(
            issue("chunk_id_missing", "Embedding runtime requires a knowledge chunk id.", component="embedding_session")
        )
    if resolved_dimensions < 0:
        blocking_issues.append(
            issue(
                "embedding_dimensions_invalid",
                "Embedding dimensions must be greater than or equal to zero.",
                component="embedding_session",
            )
        )
    if resolved_dimensions == 0:
        warnings.append(
            issue(
                "embedding_vector_not_generated",
                "Embedding foundation persists metadata only and does not generate numeric vectors.",
                component="embedding_session",
                severity="warning",
            )
        )
    ready = not blocking_issues
    return EmbeddingSession(
        embedding_session_id=_stable_session_id(
            chunk_id=chunk_id, model_name=resolved_model_name, model_version=resolved_model_version
        ),
        chunk_id=chunk_id,
        model_name=resolved_model_name,
        model_version=resolved_model_version,
        embedding_dimensions=resolved_dimensions,
        embedding_state=EMBEDDING_STATE_READY if ready else EMBEDDING_STATE_BLOCKED,
        runtime_metadata={
            "embedding_runtime_version": EMBEDDING_RUNTIME_VERSION,
            "provider_neutral": True,
            "metadata_only": True,
            "postgresql_source_of_truth": True,
            **dict(runtime_metadata or {}),
        },
        blocking_issues=sort_issues(blocking_issues),
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "execute_embedding_metadata",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "embedding_session_blocked",
            }
        ],
    )


def serialize_embedding_session(session: EmbeddingSession) -> dict[str, Any]:
    return {
        "embedding_session_schema_version": EMBEDDING_SESSION_SCHEMA_VERSION,
        "embedding_session_id": session.embedding_session_id,
        "chunk_id": session.chunk_id,
        "model_name": session.model_name,
        "model_version": session.model_version,
        "embedding_dimensions": session.embedding_dimensions,
        "embedding_state": session.embedding_state,
        "embedding_session_ready": session.embedding_state == EMBEDDING_STATE_READY,
        "runtime_metadata": dict(session.runtime_metadata),
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "embedding_vector_generated": False,
        "embedding_provider_called": False,
        "semantic_search_used": False,
        "postgresql_source_of_truth": True,
        "persistence_status": "not_persisted",
    }
