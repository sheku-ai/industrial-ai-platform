"""Chunk gateway from Processing Result to Chunk Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.document_chunk_session import build_chunk_session, serialize_chunk_session

CHUNK_GATEWAY_SCHEMA_VERSION = "1"
CHUNK_GATEWAY_STATUS_BLOCKED = "blocked"
CHUNK_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class DocumentChunkGateway:
    artifact_id: str | None
    processing_session_id: str | None
    chunk_session: dict[str, Any]
    gateway_status: str
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def build_document_chunk_gateway(
    processing_result: dict[str, Any],
    *,
    chunker_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunk_session = serialize_chunk_session(build_chunk_session(processing_result, chunker_config=chunker_config))
    ready = bool(chunk_session.get("chunk_session_ready"))
    gateway = DocumentChunkGateway(
        artifact_id=processing_result.get("artifact_id"),
        processing_session_id=processing_result.get("processing_session_id"),
        chunk_session=chunk_session,
        gateway_status=CHUNK_GATEWAY_STATUS_READY if ready else CHUNK_GATEWAY_STATUS_BLOCKED,
        blocking_issues=chunk_session.get("blocking_issues") or [],
        warnings=chunk_session.get("warnings") or [],
        next_available_actions=[
            {
                "action": "execute_chunk_runtime",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "chunk_session_not_ready",
                "embeddings_created": False,
                "knowledge_published": False,
                "ai_required": False,
            }
        ],
    )
    serialized = {
        "chunk_gateway_schema_version": CHUNK_GATEWAY_SCHEMA_VERSION,
        "artifact_id": gateway.artifact_id,
        "processing_session_id": gateway.processing_session_id,
        "chunk_gateway_ready": gateway.gateway_status == CHUNK_GATEWAY_STATUS_READY,
        "gateway_status": gateway.gateway_status,
        "chunk_session": dict(gateway.chunk_session),
        "blocking_issues": list(gateway.blocking_issues),
        "warnings": list(gateway.warnings),
        "next_available_actions": list(gateway.next_available_actions),
        "chunks_created": False,
        "embeddings_created": False,
        "knowledge_published": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
    return {**serialized, "chunk_gateway": serialized}
