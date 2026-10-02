"""Knowledge publication session for validated chunk results."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

KNOWLEDGE_PUBLICATION_SESSION_SCHEMA_VERSION = "1"
KNOWLEDGE_PUBLICATION_STATE_BLOCKED = "blocked"
KNOWLEDGE_PUBLICATION_STATE_READY = "ready"
KNOWLEDGE_PUBLICATION_RUNTIME_VERSION = "knowledge_publication_runtime/1.0"


@dataclass(frozen=True)
class KnowledgePublicationSession:
    publication_session_id: str | None
    publication_id: str | None
    artifact_id: str | None
    processing_session_id: str | None
    chunk_session_id: str | None
    publication_state: str
    publication_config: dict[str, Any] = field(default_factory=dict)
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


def _stable_digest(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def stable_publication_id(chunk_result: dict[str, Any]) -> str | None:
    artifact_id = chunk_result.get("artifact_id")
    chunk_session_id = chunk_result.get("chunk_session_id")
    chunks = chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else []
    if not artifact_id and not chunk_session_id:
        return None
    signature = "|".join(
        f"{chunk.get('chunk_index')}:{chunk.get('content_hash')}" for chunk in chunks if isinstance(chunk, dict)
    )
    digest = _stable_digest(
        artifact_id or "artifact:unknown",
        chunk_session_id or "chunk-session:unknown",
        signature,
    )
    return f"knowledge-publication:{digest}"


def stable_publication_session_id(chunk_result: dict[str, Any]) -> str | None:
    publication_id = stable_publication_id(chunk_result)
    if publication_id:
        return f"knowledge-publication-session:{_stable_digest(publication_id)}"
    return None


def default_publication_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(overrides or {})
    return {
        "publication_runtime_version": values.get("publication_runtime_version")
        or KNOWLEDGE_PUBLICATION_RUNTIME_VERSION,
        "store_provider_type": values.get("store_provider_type") or "memory",
        "duplicate_policy": values.get("duplicate_policy") or "reuse_existing",
        "deterministic_ids": True,
        "embeddings_enabled": False,
        "semantic_index_enabled": False,
        "ai_enabled": False,
    }


def validate_publication_session_readiness(
    chunk_result: dict[str, Any],
    *,
    publication_config: dict[str, Any],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    chunks = chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else []

    if chunk_result.get("chunk_generation_completed") is not True:
        blocking_issues.append(
            issue(
                "chunk_generation_not_completed",
                "Publication requires chunk_generation_completed=true.",
                component="chunk_result",
            )
        )
    if chunk_result.get("chunks_created") is not True:
        blocking_issues.append(
            issue("chunks_not_created", "Publication requires chunks_created=true.", component="chunk_result")
        )
    if int(chunk_result.get("chunk_count") or 0) < 1:
        blocking_issues.append(
            issue("chunk_count_empty", "Publication requires chunk_count >= 1.", component="chunk_result")
        )
    if not chunks:
        blocking_issues.append(
            issue("chunks_missing", "Publication requires a non-empty chunks list.", component="chunk_result")
        )
    if chunk_result.get("chunk_status") not in {None, "completed"}:
        blocking_issues.append(
            issue(
                "chunk_runtime_failed",
                "Publication cannot run when chunk runtime did not complete.",
                component="chunk_result",
            )
        )
    if publication_config.get("store_provider_type") != "memory":
        blocking_issues.append(
            issue(
                "knowledge_store_not_supported",
                "Publication runtime foundation currently supports only the memory reference store.",
                component="knowledge_store",
                item_id=str(publication_config.get("store_provider_type")),
            )
        )
    if chunk_result.get("embeddings_created"):
        warnings.append(
            issue(
                "embeddings_present_unexpected",
                "Publication runtime does not require embeddings and will ignore embedding state.",
                component="publication_runtime",
                severity="warning",
            )
        )

    seen_indexes: set[int] = set()
    for position, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            blocking_issues.append(
                issue(
                    "chunk_invalid",
                    "Publication requires chunk entries to be objects.",
                    component="chunk_result",
                    item_id=str(position),
                )
            )
            continue
        chunk_index = chunk.get("chunk_index")
        if not isinstance(chunk_index, int):
            blocking_issues.append(
                issue(
                    "chunk_index_missing",
                    "Each chunk requires chunk_index.",
                    component="chunk_result",
                    item_id=str(position),
                )
            )
        elif chunk_index in seen_indexes:
            blocking_issues.append(
                issue(
                    "chunk_index_duplicate",
                    "Chunk indexes must be unique before publication.",
                    component="chunk_result",
                    item_id=str(chunk_index),
                )
            )
        else:
            seen_indexes.add(chunk_index)
        if not chunk.get("content_hash"):
            blocking_issues.append(
                issue(
                    "content_hash_missing",
                    "Each chunk requires content_hash.",
                    component="chunk_result",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("semantic_hash"):
            blocking_issues.append(
                issue(
                    "semantic_hash_missing",
                    "Each chunk requires semantic_hash.",
                    component="chunk_result",
                    item_id=str(chunk_index),
                )
            )
        text = chunk.get("content")
        if not isinstance(text, str) or not text.strip():
            blocking_issues.append(
                issue(
                    "chunk_text_missing",
                    "Each chunk requires non-empty text.",
                    component="chunk_result",
                    item_id=str(chunk_index),
                )
            )

    return {
        "validation_status": KNOWLEDGE_PUBLICATION_STATE_BLOCKED
        if blocking_issues
        else KNOWLEDGE_PUBLICATION_STATE_READY,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
    }


def build_knowledge_publication_session(
    chunk_result: dict[str, Any],
    *,
    publication_config: dict[str, Any] | None = None,
) -> KnowledgePublicationSession:
    config = default_publication_config(publication_config)
    validation = validate_publication_session_readiness(chunk_result, publication_config=config)
    ready = not validation["blocking_issues"]
    return KnowledgePublicationSession(
        publication_session_id=stable_publication_session_id(chunk_result),
        publication_id=stable_publication_id(chunk_result),
        artifact_id=chunk_result.get("artifact_id"),
        processing_session_id=chunk_result.get("processing_session_id"),
        chunk_session_id=chunk_result.get("chunk_session_id"),
        publication_state=KNOWLEDGE_PUBLICATION_STATE_READY if ready else KNOWLEDGE_PUBLICATION_STATE_BLOCKED,
        publication_config=config,
        blocking_issues=validation["blocking_issues"],
        warnings=validation["warnings"],
        next_available_actions=[
            {
                "action": "publish_to_knowledge",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "publication_session_validation_blocked",
                "embeddings_created": False,
                "semantic_index_created": False,
                "ai_required": False,
            }
        ],
    )


def serialize_knowledge_publication_session(session: KnowledgePublicationSession) -> dict[str, Any]:
    return {
        "knowledge_publication_session_schema_version": KNOWLEDGE_PUBLICATION_SESSION_SCHEMA_VERSION,
        "publication_session_id": session.publication_session_id,
        "publication_id": session.publication_id,
        "artifact_id": session.artifact_id,
        "processing_session_id": session.processing_session_id,
        "chunk_session_id": session.chunk_session_id,
        "publication_state": session.publication_state,
        "publication_session_ready": session.publication_state == KNOWLEDGE_PUBLICATION_STATE_READY,
        "publication_config": dict(session.publication_config),
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "knowledge_published": False,
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
