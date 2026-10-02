"""Executable Knowledge Publication Runtime for chunk results."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.knowledge_publication_gateway import build_knowledge_publication_gateway
from app.services.knowledge_publication_session import (
    KNOWLEDGE_PUBLICATION_STATE_BLOCKED,
    issue,
    sort_issues,
)
from app.services.knowledge_store_memory import get_memory_knowledge_store

KNOWLEDGE_PUBLICATION_RUNTIME_SCHEMA_VERSION = "1"
PUBLISHED_CHUNK_SCHEMA_VERSION = "1"
PUBLICATION_STATUS_BLOCKED = "blocked"
PUBLICATION_STATUS_COMPLETED = "completed"
PUBLICATION_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PublishedChunk:
    published_chunk_id: str
    publication_id: str
    artifact_id: str | None
    document_record_id: str | None
    document_version_id: str | None
    processing_session_id: str | None
    chunk_session_id: str | None
    chunk_index: int
    text: str
    content_hash: str
    semantic_hash: str
    content_type: str | None
    chunk_scope: str | None
    source_content_sha256: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    published_at: str | None = None


@dataclass(frozen=True)
class KnowledgePublicationRuntimeResult:
    publication_id: str | None
    publication_session_id: str | None
    artifact_id: str | None
    processing_session_id: str | None
    chunk_session_id: str | None
    publication_status: str
    published_chunks: list[dict[str, Any]] = field(default_factory=list)
    publication_validation: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _stable_digest(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def stable_published_chunk_id(
    *, publication_id: str, artifact_id: str | None, chunk_index: int, content_hash: str
) -> str:
    digest = _stable_digest(publication_id, artifact_id or "artifact:unknown", chunk_index, content_hash)
    return f"published-chunk:{digest}"


def _published_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _serialize_published_chunk(chunk: PublishedChunk) -> dict[str, Any]:
    return {
        "published_chunk_schema_version": PUBLISHED_CHUNK_SCHEMA_VERSION,
        "published_chunk_id": chunk.published_chunk_id,
        "publication_id": chunk.publication_id,
        "artifact_id": chunk.artifact_id,
        "document_record_id": chunk.document_record_id,
        "document_version_id": chunk.document_version_id,
        "processing_session_id": chunk.processing_session_id,
        "chunk_session_id": chunk.chunk_session_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "content_hash": chunk.content_hash,
        "semantic_hash": chunk.semantic_hash,
        "content_type": chunk.content_type,
        "chunk_scope": chunk.chunk_scope,
        "source_content_sha256": chunk.source_content_sha256,
        "metadata": dict(chunk.metadata),
        "published_at": chunk.published_at,
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def build_published_chunk_records(
    chunk_result: dict[str, Any],
    *,
    publication_id: str,
) -> list[dict[str, Any]]:
    chunks = chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else []
    published_at = _published_at()
    records: list[dict[str, Any]] = []
    for chunk in sorted(chunks, key=lambda item: int(item.get("chunk_index"))):
        chunk_index = int(chunk.get("chunk_index"))
        content_hash = str(chunk.get("content_hash"))
        record = PublishedChunk(
            published_chunk_id=stable_published_chunk_id(
                publication_id=publication_id,
                artifact_id=chunk.get("artifact_id"),
                chunk_index=chunk_index,
                content_hash=content_hash,
            ),
            publication_id=publication_id,
            artifact_id=chunk.get("artifact_id"),
            document_record_id=chunk.get("document_record_id") or chunk_result.get("document_record_id"),
            document_version_id=chunk.get("document_version_id") or chunk_result.get("document_version_id"),
            processing_session_id=chunk.get("processing_session_id"),
            chunk_session_id=chunk_result.get("chunk_session_id"),
            chunk_index=chunk_index,
            text=str(chunk.get("content")),
            content_hash=content_hash,
            semantic_hash=str(chunk.get("semantic_hash")),
            content_type=chunk.get("content_type"),
            chunk_scope=chunk.get("chunk_scope"),
            source_content_sha256=chunk.get("source_content_sha256"),
            metadata={
                "char_count": chunk.get("char_count"),
                "line_count": chunk.get("line_count"),
                "chunker_version": chunk.get("chunker_version"),
                "publication_source": "chunk_result",
            },
            published_at=published_at,
        )
        records.append(_serialize_published_chunk(record))
    return records


def validate_publication_result(
    *,
    chunk_result: dict[str, Any],
    published_chunks: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    expected_count = int(chunk_result.get("chunk_count") or 0)
    seen_indexes: set[int] = set()

    if duplicates:
        warnings.append(
            issue(
                "published_chunks_reused",
                "One or more chunks already existed in the memory store and were reused.",
                component="knowledge_store",
                severity="warning",
            )
        )
    if len(published_chunks) != expected_count:
        blocking_issues.append(
            issue(
                "published_chunk_count_mismatch",
                "published_chunk_count must equal chunk_count.",
                component="publication_validation",
            )
        )
    for position, chunk in enumerate(published_chunks):
        chunk_index = chunk.get("chunk_index")
        if not isinstance(chunk_index, int):
            blocking_issues.append(
                issue(
                    "chunk_index_missing",
                    "Each published chunk requires chunk_index.",
                    component="publication_validation",
                    item_id=str(position),
                )
            )
            continue
        if chunk_index in seen_indexes:
            blocking_issues.append(
                issue(
                    "chunk_index_duplicate",
                    "Published chunk indexes must be unique.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        seen_indexes.add(chunk_index)
        if not chunk.get("published_chunk_id"):
            blocking_issues.append(
                issue(
                    "published_chunk_id_missing",
                    "Each published chunk requires published_chunk_id.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("publication_id"):
            blocking_issues.append(
                issue(
                    "publication_id_missing",
                    "Each published chunk requires publication_id.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("content_hash"):
            blocking_issues.append(
                issue(
                    "content_hash_missing",
                    "Each published chunk requires content_hash.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("document_record_id") or not chunk.get("document_version_id"):
            blocking_issues.append(
                issue(
                    "RESOURCE_LINEAGE_INCOMPLETE",
                    "Published chunks require document_record_id and document_version_id lineage.",
                    component="publication_lineage",
                    item_id=str(chunk_index),
                )
            )
        if not chunk.get("semantic_hash"):
            blocking_issues.append(
                issue(
                    "semantic_hash_missing",
                    "Each published chunk requires semantic_hash.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        text = chunk.get("text")
        if not isinstance(text, str) or not text.strip():
            blocking_issues.append(
                issue(
                    "published_text_empty",
                    "Published chunks cannot contain empty text.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )
        if (
            chunk.get("embeddings_created") is not False
            or chunk.get("semantic_index_created") is not False
            or chunk.get("ai_required") is not False
        ):
            blocking_issues.append(
                issue(
                    "semantic_ai_flags_enabled",
                    "Publication must keep embeddings, semantic index, and AI disabled.",
                    component="publication_validation",
                    item_id=str(chunk_index),
                )
            )

    expected_indexes = list(range(expected_count))
    actual_indexes = [chunk.get("chunk_index") for chunk in published_chunks]
    if actual_indexes != expected_indexes:
        blocking_issues.append(
            issue(
                "published_chunk_order_unstable",
                "Published chunks must preserve contiguous chunk order.",
                component="publication_validation",
            )
        )

    return {
        "publication_validation_schema_version": "1",
        "validation_status": PUBLICATION_STATUS_BLOCKED if blocking_issues else "valid",
        "valid": not blocking_issues,
        "expected_chunk_count": expected_count,
        "published_chunk_count": len(published_chunks),
        "duplicate_count": len(duplicates),
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
    }


def serialize_publication_runtime_result(result: KnowledgePublicationRuntimeResult) -> dict[str, Any]:
    completed = result.publication_status == PUBLICATION_STATUS_COMPLETED
    payload = {
        "knowledge_publication_runtime_schema_version": KNOWLEDGE_PUBLICATION_RUNTIME_SCHEMA_VERSION,
        "publication_id": result.publication_id,
        "publication_session_id": result.publication_session_id,
        "artifact_id": result.artifact_id,
        "document_record_id": (
            result.published_chunks[0].get("document_record_id") if result.published_chunks else None
        ),
        "document_version_id": (
            result.published_chunks[0].get("document_version_id") if result.published_chunks else None
        ),
        "processing_session_id": result.processing_session_id,
        "chunk_session_id": result.chunk_session_id,
        "publication_status": result.publication_status,
        "publication_completed": completed,
        "publication_succeeded": completed,
        "knowledge_published": completed and bool(result.published_chunks),
        "published_chunk_count": len(result.published_chunks),
        "published_chunks": list(result.published_chunks),
        "publication_validation": dict(result.publication_validation),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**payload, "publication_result": payload}


def build_knowledge_publication(
    chunk_result: dict[str, Any],
    *,
    publication_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gateway = build_knowledge_publication_gateway(chunk_result, publication_config=publication_config)
    publication_session = (
        gateway.get("publication_session") if isinstance(gateway.get("publication_session"), dict) else {}
    )
    warnings = list(gateway.get("warnings") or [])

    if gateway.get("blocking_issues"):
        result = KnowledgePublicationRuntimeResult(
            publication_id=publication_session.get("publication_id"),
            publication_session_id=publication_session.get("publication_session_id"),
            artifact_id=chunk_result.get("artifact_id"),
            processing_session_id=chunk_result.get("processing_session_id"),
            chunk_session_id=chunk_result.get("chunk_session_id"),
            publication_status=PUBLICATION_STATUS_BLOCKED,
            published_chunks=[],
            publication_validation={
                "publication_validation_schema_version": "1",
                "validation_status": KNOWLEDGE_PUBLICATION_STATE_BLOCKED,
                "valid": False,
                "expected_chunk_count": int(chunk_result.get("chunk_count") or 0),
                "published_chunk_count": 0,
                "blocking_issues": gateway.get("blocking_issues") or [],
                "warnings": warnings,
                "embeddings_created": False,
                "semantic_index_created": False,
                "ai_required": False,
            },
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=warnings,
            next_available_actions=[
                {
                    "action": "publish_to_knowledge",
                    "available": False,
                    "status": "blocked",
                    "reason": "publication_gateway_validation_blocked",
                }
            ],
        )
        return {**serialize_publication_runtime_result(result), "publication_gateway": gateway}

    publication_id = str(publication_session.get("publication_id"))
    records = build_published_chunk_records(chunk_result, publication_id=publication_id)
    published_chunks, duplicates = get_memory_knowledge_store().publish_chunks(records)
    validation = validate_publication_result(
        chunk_result=chunk_result,
        published_chunks=published_chunks,
        duplicates=duplicates,
    )
    warnings.extend(validation.get("warnings") or [])
    status = PUBLICATION_STATUS_COMPLETED if validation.get("valid") else PUBLICATION_STATUS_FAILED
    result = KnowledgePublicationRuntimeResult(
        publication_id=publication_id,
        publication_session_id=publication_session.get("publication_session_id"),
        artifact_id=chunk_result.get("artifact_id"),
        processing_session_id=chunk_result.get("processing_session_id"),
        chunk_session_id=chunk_result.get("chunk_session_id"),
        publication_status=status,
        published_chunks=published_chunks,
        publication_validation=validation,
        blocking_issues=validation.get("blocking_issues") or [],
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "generate_embeddings",
                "available": False,
                "status": "blocked",
                "reason": "embeddings_not_in_publication_runtime_scope",
            },
            {
                "action": "create_semantic_index",
                "available": False,
                "status": "blocked",
                "reason": "semantic_index_not_in_publication_runtime_scope",
            },
        ],
    )
    return {**serialize_publication_runtime_result(result), "publication_gateway": gateway}
