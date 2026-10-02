"""Executable Chunk Runtime for text/plain processing results."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.document_chunk_gateway import build_document_chunk_gateway
from app.services.document_chunk_session import (
    CHUNK_SESSION_STATE_BLOCKED,
    CHUNKER_VERSION,
    DEFAULT_CHUNK_SCOPE,
    DEFAULT_MAX_CHARS,
    issue,
    sort_issues,
)

CHUNK_RUNTIME_SCHEMA_VERSION = "1"
CHUNK_RESULT_SCHEMA_VERSION = "1"
CHUNK_STATUS_BLOCKED = "blocked"
CHUNK_STATUS_COMPLETED = "completed"
CHUNK_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class DocumentChunk:
    artifact_id: str | None
    document_record_id: str | None
    document_version_id: str | None
    processing_session_id: str | None
    source_content_sha256: str | None
    chunk_index: int
    content: str
    content_hash: str
    semantic_hash: str
    char_count: int
    line_count: int
    content_type: str | None
    chunk_scope: str
    chunker_version: str


@dataclass(frozen=True)
class DocumentChunkRuntimeResult:
    artifact_id: str | None
    processing_session_id: str | None
    chunk_session_id: str | None
    chunk_status: str
    chunks: list[dict[str, Any]] = field(default_factory=list)
    chunk_validation: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _semantic_normalize(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _split_long_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(word) <= max_chars:
            current = word
            continue
        for start in range(0, len(word), max_chars):
            part = word[start : start + max_chars]
            if len(part) == max_chars:
                chunks.append(part)
            else:
                current = part
    if current:
        chunks.append(current)
    return chunks


def generate_text_chunks(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Generate deterministic chunks from normalized parsed text."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    if not blocks:
        blocks = [line.strip() for line in normalized.splitlines() if line.strip()]

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        chunks.extend(_split_long_text(block, max_chars=max_chars))
    if current:
        chunks.append(current)
    return chunks


def _serialize_chunk(chunk: DocumentChunk) -> dict[str, Any]:
    return {
        "chunk_schema_version": CHUNK_RESULT_SCHEMA_VERSION,
        "artifact_id": chunk.artifact_id,
        "document_record_id": chunk.document_record_id,
        "document_version_id": chunk.document_version_id,
        "processing_session_id": chunk.processing_session_id,
        "source_content_sha256": chunk.source_content_sha256,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "semantic_hash": chunk.semantic_hash,
        "char_count": chunk.char_count,
        "line_count": chunk.line_count,
        "content_type": chunk.content_type,
        "chunk_scope": chunk.chunk_scope,
        "chunker_version": chunk.chunker_version,
        "embeddings_created": False,
        "knowledge_published": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def build_chunk_records(
    processing_result: dict[str, Any],
    *,
    chunker_config: dict[str, Any],
) -> list[dict[str, Any]]:
    text = processing_result.get("parsed_text") if isinstance(processing_result.get("parsed_text"), str) else ""
    max_chars = int(chunker_config.get("max_chars") or DEFAULT_MAX_CHARS)
    chunk_scope = chunker_config.get("chunk_scope") or DEFAULT_CHUNK_SCOPE
    chunker_version = chunker_config.get("chunker_version") or CHUNKER_VERSION
    content_type = processing_result.get("source_content_type")
    chunks = []
    for index, content in enumerate(generate_text_chunks(text, max_chars=max_chars)):
        chunk = DocumentChunk(
            artifact_id=processing_result.get("artifact_id"),
            document_record_id=processing_result.get("document_record_id"),
            document_version_id=processing_result.get("document_version_id"),
            processing_session_id=processing_result.get("processing_session_id"),
            source_content_sha256=processing_result.get("content_sha256"),
            chunk_index=index,
            content=content,
            content_hash=_sha256_text(content),
            semantic_hash=_sha256_text(_semantic_normalize(content)),
            char_count=len(content),
            line_count=_line_count(content),
            content_type=content_type,
            chunk_scope=chunk_scope,
            chunker_version=chunker_version,
        )
        chunks.append(_serialize_chunk(chunk))
    return chunks


def validate_generated_chunks(
    chunks: list[dict[str, Any]],
    *,
    max_chars: int,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    previous_index = -1

    if not chunks:
        blocking_issues.append(issue("chunks_empty", "Chunk runtime produced no chunks.", component="chunk_validation"))

    for position, chunk in enumerate(chunks):
        chunk_index = chunk.get("chunk_index")
        if not isinstance(chunk_index, int):
            blocking_issues.append(
                issue(
                    "chunk_index_missing",
                    "Each chunk requires an integer chunk_index.",
                    component="chunk_validation",
                    item_id=str(position),
                )
            )
            continue
        if chunk_index in seen_indexes:
            blocking_issues.append(
                issue(
                    "chunk_index_duplicate",
                    "Chunk indexes must be unique.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        seen_indexes.add(chunk_index)
        if chunk_index <= previous_index:
            blocking_issues.append(
                issue(
                    "chunk_order_unstable",
                    "Chunk indexes must be strictly increasing.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        previous_index = chunk_index

        content = chunk.get("content")
        if not isinstance(content, str) or not content.strip():
            blocking_issues.append(
                issue(
                    "chunk_text_empty",
                    "Generated chunks cannot be empty.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        if isinstance(content, str) and len(content) > max_chars:
            blocking_issues.append(
                issue(
                    "chunk_text_too_large",
                    "Generated chunk exceeds max_chars.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("content_hash"):
            blocking_issues.append(
                issue(
                    "content_hash_missing",
                    "Each chunk requires content_hash.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("semantic_hash"):
            blocking_issues.append(
                issue(
                    "semantic_hash_missing",
                    "Each chunk requires semantic_hash.",
                    component="chunk_validation",
                    item_id=str(chunk_index),
                )
            )
        if chunk.get("char_count") != (len(content) if isinstance(content, str) else 0):
            warnings.append(
                issue(
                    "char_count_mismatch",
                    "Chunk char_count does not match content length.",
                    component="chunk_validation",
                    severity="warning",
                    item_id=str(chunk_index),
                )
            )

    expected_indexes = list(range(len(chunks)))
    actual_indexes = [chunk.get("chunk_index") for chunk in chunks]
    if actual_indexes != expected_indexes:
        blocking_issues.append(
            issue(
                "chunk_index_sequence_invalid",
                "Chunk indexes must start at 0 and be contiguous.",
                component="chunk_validation",
            )
        )

    return {
        "chunk_validation_schema_version": "1",
        "validation_status": CHUNK_STATUS_BLOCKED if blocking_issues else "valid",
        "valid": not blocking_issues,
        "chunk_count": len(chunks),
        "max_chars": max_chars,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
    }


def serialize_chunk_runtime_result(result: DocumentChunkRuntimeResult) -> dict[str, Any]:
    completed = result.chunk_status == CHUNK_STATUS_COMPLETED
    first_chunk = result.chunks[0] if result.chunks else {}
    payload = {
        "chunk_runtime_schema_version": CHUNK_RUNTIME_SCHEMA_VERSION,
        "artifact_id": result.artifact_id,
        "document_record_id": first_chunk.get("document_record_id"),
        "document_version_id": first_chunk.get("document_version_id"),
        "processing_session_id": result.processing_session_id,
        "chunk_session_id": result.chunk_session_id,
        "chunk_status": result.chunk_status,
        "chunk_generation_completed": completed,
        "chunks_created": completed and bool(result.chunks),
        "chunk_count": len(result.chunks),
        "chunks": list(result.chunks),
        "chunk_validation": dict(result.chunk_validation),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "embeddings_created": False,
        "knowledge_published": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**payload, "chunk_result": payload}


def build_document_chunk_generation(
    processing_result: dict[str, Any],
    *,
    chunker_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gateway = build_document_chunk_gateway(processing_result, chunker_config=chunker_config)
    chunk_session = gateway.get("chunk_session") if isinstance(gateway.get("chunk_session"), dict) else {}
    config = chunk_session.get("chunker_config") if isinstance(chunk_session.get("chunker_config"), dict) else {}
    warnings = list(gateway.get("warnings") or [])
    if gateway.get("blocking_issues"):
        result = DocumentChunkRuntimeResult(
            artifact_id=processing_result.get("artifact_id"),
            processing_session_id=processing_result.get("processing_session_id"),
            chunk_session_id=chunk_session.get("chunk_session_id"),
            chunk_status=CHUNK_STATUS_BLOCKED,
            chunks=[],
            chunk_validation={
                "chunk_validation_schema_version": "1",
                "validation_status": CHUNK_SESSION_STATE_BLOCKED,
                "valid": False,
                "chunk_count": 0,
                "blocking_issues": gateway.get("blocking_issues") or [],
                "warnings": warnings,
            },
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=warnings,
            next_available_actions=[
                {
                    "action": "generate_chunks",
                    "available": False,
                    "status": "blocked",
                    "reason": "chunk_gateway_validation_blocked",
                }
            ],
        )
        return {**serialize_chunk_runtime_result(result), "chunk_gateway": gateway}

    chunks = build_chunk_records(processing_result, chunker_config=config)
    validation = validate_generated_chunks(chunks, max_chars=int(config.get("max_chars") or DEFAULT_MAX_CHARS))
    warnings.extend(validation.get("warnings") or [])
    status = CHUNK_STATUS_COMPLETED if validation.get("valid") else CHUNK_STATUS_FAILED
    result = DocumentChunkRuntimeResult(
        artifact_id=processing_result.get("artifact_id"),
        processing_session_id=processing_result.get("processing_session_id"),
        chunk_session_id=chunk_session.get("chunk_session_id"),
        chunk_status=status,
        chunks=chunks,
        chunk_validation=validation,
        blocking_issues=validation.get("blocking_issues") or [],
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "generate_embeddings",
                "available": False,
                "status": "blocked",
                "reason": "embeddings_not_in_chunk_runtime_scope",
            },
            {
                "action": "publish_to_knowledge",
                "available": True,
                "status": "ready",
                "reason": "chunk_result_available",
                "knowledge_published": False,
            },
        ],
    )
    return {**serialize_chunk_runtime_result(result), "chunk_gateway": gateway}
