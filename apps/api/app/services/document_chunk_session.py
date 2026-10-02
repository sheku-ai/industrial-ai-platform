"""Chunk session foundation for parsed document text.

The chunk domain starts after Processing has produced parsed text. It remains
provider-neutral and non-persistent: generated chunks are runtime artifacts only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

CHUNK_SESSION_SCHEMA_VERSION = "1"
CHUNK_SESSION_STATE_BLOCKED = "blocked"
CHUNK_SESSION_STATE_READY = "ready"
CHUNKER_VERSION = "text_chunker/1.0"
DEFAULT_CHUNK_SCOPE = "document_text"
DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 0


@dataclass(frozen=True)
class DocumentChunkSession:
    chunk_session_id: str | None
    artifact_id: str | None
    processing_session_id: str | None
    source_content_sha256: str | None
    content_type: str | None
    chunk_session_state: str
    chunker_config: dict[str, Any] = field(default_factory=dict)
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


def stable_chunk_session_id(*, artifact_id: str | None, processing_session_id: str | None) -> str | None:
    if artifact_id:
        return f"chunk-session:{artifact_id}"
    if processing_session_id:
        digest = hashlib.sha256(processing_session_id.encode("utf-8")).hexdigest()[:24]
        return f"chunk-session:{digest}"
    return None


def default_chunker_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(overrides or {})
    max_chars = values.get("max_chars", DEFAULT_MAX_CHARS)
    overlap_chars = values.get("overlap_chars", DEFAULT_OVERLAP_CHARS)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    try:
        overlap_chars = int(overlap_chars)
    except (TypeError, ValueError):
        overlap_chars = DEFAULT_OVERLAP_CHARS
    max_chars = max(1, max_chars)
    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    return {
        "chunker_version": values.get("chunker_version") or CHUNKER_VERSION,
        "chunk_scope": values.get("chunk_scope") or DEFAULT_CHUNK_SCOPE,
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "split_strategy": values.get("split_strategy") or "paragraph_then_line_then_word",
        "deterministic": True,
    }


def validate_chunk_session_readiness(
    processing_result: dict[str, Any],
    *,
    chunker_config: dict[str, Any],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not processing_result.get("artifact_id"):
        blocking_issues.append(
            issue("artifact_id_missing", "Chunk runtime requires an artifact_id.", component="chunk_session")
        )
    if not processing_result.get("processing_session_id"):
        blocking_issues.append(
            issue(
                "processing_session_missing",
                "Chunk runtime requires a processing_session_id.",
                component="chunk_session",
            )
        )
    if processing_result.get("processing_completed") is not True:
        blocking_issues.append(
            issue(
                "processing_not_completed",
                "Chunk runtime requires processing_completed=true.",
                component="processing_result",
            )
        )
    if processing_result.get("text_extracted") is not True:
        blocking_issues.append(
            issue("text_not_extracted", "Chunk runtime requires text_extracted=true.", component="processing_result")
        )
    parsed_text = processing_result.get("parsed_text")
    if not isinstance(parsed_text, str) or not parsed_text.strip():
        blocking_issues.append(
            issue(
                "parsed_text_missing",
                "Chunk runtime requires non-empty processing_result.parsed_text.",
                component="processing_result",
            )
        )
    content_type = (processing_result.get("source_content_type") or "").split(";", 1)[0].strip().lower()
    if content_type != "text/plain":
        blocking_issues.append(
            issue(
                "content_type_not_supported",
                "Chunk runtime foundation currently supports only text/plain processing results.",
                component="chunk_runtime",
                item_id=content_type or "unknown",
            )
        )
    if not processing_result.get("content_sha256"):
        warnings.append(
            issue(
                "source_content_hash_missing",
                "Chunk runtime will use parsed text as source even though content_sha256 is missing.",
                component="processing_result",
                severity="warning",
            )
        )
    if chunker_config.get("overlap_chars"):
        warnings.append(
            issue(
                "chunk_overlap_disabled_for_foundation",
                "Chunk runtime foundation records overlap config but emits non-overlapping chunks.",
                component="chunk_runtime",
                severity="warning",
            )
        )

    return {
        "validation_status": CHUNK_SESSION_STATE_BLOCKED if blocking_issues else CHUNK_SESSION_STATE_READY,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
    }


def build_chunk_session(
    processing_result: dict[str, Any],
    *,
    chunker_config: dict[str, Any] | None = None,
) -> DocumentChunkSession:
    config = default_chunker_config(chunker_config)
    validation = validate_chunk_session_readiness(processing_result, chunker_config=config)
    ready = not validation["blocking_issues"]
    return DocumentChunkSession(
        chunk_session_id=stable_chunk_session_id(
            artifact_id=processing_result.get("artifact_id"),
            processing_session_id=processing_result.get("processing_session_id"),
        ),
        artifact_id=processing_result.get("artifact_id"),
        processing_session_id=processing_result.get("processing_session_id"),
        source_content_sha256=processing_result.get("content_sha256"),
        content_type=processing_result.get("source_content_type"),
        chunk_session_state=CHUNK_SESSION_STATE_READY if ready else CHUNK_SESSION_STATE_BLOCKED,
        chunker_config=config,
        blocking_issues=validation["blocking_issues"],
        warnings=validation["warnings"],
        next_available_actions=[
            {
                "action": "generate_chunks",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "chunk_session_validation_blocked",
                "embeddings_created": False,
                "knowledge_published": False,
                "ai_required": False,
            }
        ],
    )


def serialize_chunk_session(session: DocumentChunkSession) -> dict[str, Any]:
    return {
        "chunk_session_schema_version": CHUNK_SESSION_SCHEMA_VERSION,
        "chunk_session_id": session.chunk_session_id,
        "artifact_id": session.artifact_id,
        "processing_session_id": session.processing_session_id,
        "source_content_sha256": session.source_content_sha256,
        "content_type": session.content_type,
        "chunk_session_state": session.chunk_session_state,
        "chunk_session_ready": session.chunk_session_state == CHUNK_SESSION_STATE_READY,
        "chunker_config": dict(session.chunker_config),
        "blocking_issues": list(session.blocking_issues),
        "warnings": list(session.warnings),
        "next_available_actions": list(session.next_available_actions),
        "chunks_created": False,
        "embeddings_created": False,
        "knowledge_published": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
