"""Runtime Persistence gateway and record materialization."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.services.runtime_persistence_session import (
    build_runtime_persistence_session,
    serialize_runtime_persistence_session,
)

RUNTIME_PERSISTENCE_GATEWAY_SCHEMA_VERSION = "1"
RUNTIME_PERSISTENCE_GATEWAY_STATUS_BLOCKED = "blocked"
RUNTIME_PERSISTENCE_GATEWAY_STATUS_READY = "ready"


@dataclass(frozen=True)
class RuntimePersistenceRecordDescriptor:
    runtime_domain: str
    record_type: str
    record_key: str
    artifact_id: str | None
    processing_session_id: str | None
    correlation_id: str | None
    provider: str | None
    execution_status: str | None
    content_hash: str | None
    summary: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


def sanitize_for_jsonb(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_for_jsonb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_jsonb(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_jsonb(item) for item in value]
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return {
            "__type": "bytes",
            "encoding": "base64",
            "size_bytes": len(raw),
            "data": base64.b64encode(raw).decode("ascii"),
        }
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _stable_key(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _artifact_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    return str(payload.get("artifact_id") or fallback) if payload.get("artifact_id") or fallback else None


def _processing_session_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    return (
        str(payload.get("processing_session_id") or fallback)
        if payload.get("processing_session_id") or fallback
        else None
    )


def _record(
    *,
    runtime_domain: str,
    record_type: str,
    record_key: str,
    payload: dict[str, Any],
    artifact_id: str | None = None,
    processing_session_id: str | None = None,
    provider: str | None = None,
    execution_status: str | None = None,
    content_hash: str | None = None,
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> RuntimePersistenceRecordDescriptor:
    return RuntimePersistenceRecordDescriptor(
        runtime_domain=runtime_domain,
        record_type=record_type,
        record_key=record_key,
        artifact_id=artifact_id,
        processing_session_id=processing_session_id,
        correlation_id=correlation_id,
        provider=provider,
        execution_status=execution_status,
        content_hash=content_hash,
        summary=sanitize_for_jsonb(summary or {}),
        payload=sanitize_for_jsonb(payload),
        validation=sanitize_for_jsonb(validation or {}),
        metrics=sanitize_for_jsonb(metrics or {}),
    )


def _storage_records(
    storage_payload: Any, *, execution_id: str, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    items = _as_list(storage_payload) if isinstance(storage_payload, list) else [storage_payload]
    records: list[RuntimePersistenceRecordDescriptor] = []
    for position, item in enumerate(items):
        payload = _as_dict(item)
        if not payload:
            continue
        request = _as_dict(payload.get("execution_request"))
        result = _as_dict(payload.get("result_descriptor"))
        verification = _as_dict(payload.get("verification_descriptor"))
        provider_descriptor = _as_dict(payload.get("provider_descriptor") or request.get("provider_descriptor"))
        resolved_artifact_id = _artifact_id(payload, artifact_id)
        provider = (
            payload.get("storage_provider_type")
            or provider_descriptor.get("provider_type")
            or provider_descriptor.get("provider_name")
        )
        operation = request.get("requested_operation") or payload.get("requested_operation") or f"operation:{position}"
        session_key = (
            payload.get("execution_session_id") or request.get("request_id") or _stable_key(execution_id, "storage")
        )
        base_key = f"{session_key}:{operation}:{position}"
        records.append(
            _record(
                runtime_domain="storage",
                record_type="execution_request",
                record_key=f"{base_key}:request",
                artifact_id=resolved_artifact_id,
                provider=str(provider) if provider else None,
                execution_status=str(
                    payload.get("storage_execution_result_status") or result.get("result_status") or "requested"
                ),
                content_hash=payload.get("checksum") or result.get("checksum"),
                payload=request or payload,
                summary={
                    "operation": operation,
                    "storage_verified": bool(payload.get("storage_verified")),
                    "content_type": payload.get("content_type") or result.get("content_type"),
                    "content_length": payload.get("content_length") or result.get("content_length"),
                    "checksum": payload.get("checksum") or result.get("checksum"),
                },
                validation=_as_dict(payload.get("validation")),
            )
        )
        if result:
            records.append(
                _record(
                    runtime_domain="storage",
                    record_type="execution_result",
                    record_key=f"{base_key}:result",
                    artifact_id=resolved_artifact_id,
                    provider=str(provider) if provider else None,
                    execution_status=str(
                        result.get("result_status") or payload.get("storage_execution_result_status") or "executed"
                    ),
                    content_hash=result.get("checksum") or payload.get("checksum"),
                    payload=result,
                    summary={
                        "object_stored": bool(result.get("object_stored")),
                        "file_uploaded": bool(result.get("file_uploaded")),
                        "checksum_calculated": bool(result.get("checksum_calculated")),
                        "content_type": result.get("content_type"),
                        "content_length": result.get("content_length"),
                    },
                    validation=_as_dict(payload.get("result_validation")),
                )
            )
        if verification:
            records.append(
                _record(
                    runtime_domain="storage",
                    record_type="verification_result",
                    record_key=f"{base_key}:verification",
                    artifact_id=resolved_artifact_id,
                    provider=str(provider) if provider else None,
                    execution_status=str(
                        verification.get("verification_status")
                        or payload.get("storage_verification_status")
                        or "verified"
                    ),
                    content_hash=verification.get("checksum") or payload.get("checksum"),
                    payload=verification,
                    summary={
                        "storage_verified": bool(
                            verification.get("storage_verified") or payload.get("storage_verified")
                        ),
                        "object_exists": bool(verification.get("object_exists") or payload.get("object_exists")),
                        "content_type": verification.get("content_type"),
                        "content_length": verification.get("content_length"),
                    },
                    validation=_as_dict(payload.get("verification_validation")),
                )
            )
    return records


def _processing_records(
    processing: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    processing_result = _as_dict(processing.get("processing_result"))
    parser_runtime = _as_dict(processing.get("parser_runtime"))
    resolved_artifact_id = _artifact_id(processing_result, _artifact_id(processing, artifact_id))
    processing_session_id = _processing_session_id(processing_result, processing.get("processing_session_id"))
    return [
        _record(
            runtime_domain="processing",
            record_type="parser_runtime",
            record_key=processing_session_id or _stable_key(resolved_artifact_id, "parser"),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(processing.get("processing_status") or "unknown"),
            content_hash=processing_result.get("content_sha256"),
            payload=parser_runtime,
            summary={
                "parser_executed": bool(parser_runtime.get("parser_executed")),
                "parser_name": parser_runtime.get("parser_name"),
                "parser_version": parser_runtime.get("parser_version"),
            },
        ),
        _record(
            runtime_domain="processing",
            record_type="processing_result",
            record_key=processing_session_id or _stable_key(resolved_artifact_id, "processing-result"),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(processing.get("processing_status") or "unknown"),
            content_hash=processing_result.get("content_sha256"),
            payload=processing_result,
            summary={
                "processing_completed": bool(processing_result.get("processing_completed")),
                "text_extracted": bool(processing_result.get("text_extracted")),
                "text_char_count": processing_result.get("text_char_count"),
                "line_count": processing_result.get("line_count"),
                "persistence_status": processing_result.get("persistence_status"),
            },
            validation={
                "blocking_issues": processing.get("blocking_issues") or [],
                "warnings": processing.get("warnings") or [],
            },
        ),
    ]


def _chunk_records(
    chunk_generation: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    chunk_result = _as_dict(chunk_generation.get("chunk_result") or chunk_generation)
    chunk_gateway = _as_dict(chunk_generation.get("chunk_gateway"))
    chunk_session = _as_dict(chunk_gateway.get("chunk_session"))
    resolved_artifact_id = _artifact_id(chunk_result, artifact_id)
    processing_session_id = _processing_session_id(chunk_result)
    chunk_session_id = chunk_result.get("chunk_session_id") or chunk_session.get("chunk_session_id")
    records = [
        _record(
            runtime_domain="chunk",
            record_type="chunk_session",
            record_key=str(chunk_session_id or _stable_key(resolved_artifact_id, "chunk-session")),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(chunk_result.get("chunk_status") or "unknown"),
            payload=chunk_session or chunk_gateway,
            summary={
                "chunk_session_id": chunk_session_id,
                "chunk_generation_completed": bool(chunk_result.get("chunk_generation_completed")),
                "chunk_count": chunk_result.get("chunk_count"),
            },
            validation=_as_dict(chunk_result.get("chunk_validation")),
        ),
        _record(
            runtime_domain="chunk",
            record_type="chunk_result",
            record_key=str(chunk_session_id or _stable_key(resolved_artifact_id, "chunk-result")),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(chunk_result.get("chunk_status") or "unknown"),
            payload=chunk_result,
            summary={
                "chunks_created": bool(chunk_result.get("chunks_created")),
                "chunk_count": chunk_result.get("chunk_count"),
            },
            validation=_as_dict(chunk_result.get("chunk_validation")),
        ),
    ]
    for chunk in _as_list(chunk_result.get("chunks")):
        chunk_dict = _as_dict(chunk)
        chunk_index = chunk_dict.get("chunk_index")
        records.append(
            _record(
                runtime_domain="chunk",
                record_type="chunk",
                record_key=(
                    f"{chunk_session_id or resolved_artifact_id}:chunk:{chunk_index}:{chunk_dict.get('content_hash')}"
                ),
                artifact_id=_artifact_id(chunk_dict, resolved_artifact_id),
                processing_session_id=_processing_session_id(chunk_dict, processing_session_id),
                execution_status=str(chunk_result.get("chunk_status") or "unknown"),
                content_hash=chunk_dict.get("content_hash"),
                payload=chunk_dict,
                summary={
                    "chunk_index": chunk_index,
                    "semantic_hash": chunk_dict.get("semantic_hash"),
                    "char_count": chunk_dict.get("char_count"),
                    "line_count": chunk_dict.get("line_count"),
                },
            )
        )
    return records


def _publication_records(
    publication: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    publication_result = _as_dict(publication.get("publication_result") or publication)
    publication_gateway = _as_dict(publication.get("publication_gateway"))
    publication_session = _as_dict(publication_gateway.get("publication_session"))
    publication_id = publication_result.get("publication_id") or publication_session.get("publication_id")
    resolved_artifact_id = _artifact_id(publication_result, artifact_id)
    processing_session_id = _processing_session_id(publication_result)
    records = [
        _record(
            runtime_domain="knowledge_publication",
            record_type="publication_session",
            record_key=str(
                publication_session.get("publication_session_id")
                or publication_id
                or _stable_key(resolved_artifact_id, "publication-session")
            ),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(publication_result.get("publication_status") or "unknown"),
            payload=publication_session or publication_gateway,
            summary={
                "publication_id": publication_id,
                "publication_completed": bool(publication_result.get("publication_completed")),
            },
            validation=_as_dict(publication_result.get("publication_validation")),
        ),
        _record(
            runtime_domain="knowledge_publication",
            record_type="publication_result",
            record_key=str(publication_id or _stable_key(resolved_artifact_id, "publication-result")),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(publication_result.get("publication_status") or "unknown"),
            payload=publication_result,
            summary={
                "knowledge_published": bool(publication_result.get("knowledge_published")),
                "published_chunk_count": publication_result.get("published_chunk_count"),
            },
            validation=_as_dict(publication_result.get("publication_validation")),
        ),
    ]
    for published in _as_list(publication_result.get("published_chunks")):
        published_dict = _as_dict(published)
        records.append(
            _record(
                runtime_domain="knowledge_publication",
                record_type="published_chunk",
                record_key=str(
                    published_dict.get("published_chunk_id")
                    or _stable_key(publication_id, published_dict.get("chunk_index"))
                ),
                artifact_id=_artifact_id(published_dict, resolved_artifact_id),
                processing_session_id=_processing_session_id(published_dict, processing_session_id),
                execution_status=str(publication_result.get("publication_status") or "unknown"),
                content_hash=published_dict.get("content_hash"),
                payload=published_dict,
                summary={
                    "publication_id": published_dict.get("publication_id"),
                    "published_chunk_id": published_dict.get("published_chunk_id"),
                    "chunk_index": published_dict.get("chunk_index"),
                    "semantic_hash": published_dict.get("semantic_hash"),
                },
            )
        )
    return records


def _knowledge_index_records(
    index: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    index_gateway = _as_dict(index.get("knowledge_index_gateway"))
    index_session = _as_dict(index_gateway.get("index_session"))
    document = _as_dict(index.get("knowledge_document"))
    resolved_artifact_id = _artifact_id(document, _artifact_id(index_session, artifact_id))
    processing_session_id = _processing_session_id(index_session)
    index_session_id = index_session.get("index_session_id")
    records = [
        _record(
            runtime_domain="knowledge_index",
            record_type="index_session",
            record_key=str(index_session_id or _stable_key(resolved_artifact_id, "knowledge-index-session")),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(index.get("index_status") or "unknown"),
            payload=index_session or index_gateway,
            summary={
                "index_session_id": index_session_id,
                "publication_id": index_session.get("publication_id") or document.get("publication_id"),
                "index_completed": bool(index.get("index_completed")),
                "published_chunk_count": index_session.get("published_chunk_count"),
            },
        ),
        _record(
            runtime_domain="knowledge_index",
            record_type="index_result",
            record_key=str(
                document.get("knowledge_document_id") or _stable_key(resolved_artifact_id, "knowledge-index-result")
            ),
            artifact_id=resolved_artifact_id,
            processing_session_id=processing_session_id,
            execution_status=str(index.get("index_status") or "unknown"),
            payload=index,
            summary={
                "index_succeeded": bool(index.get("index_succeeded")),
                "document_indexed": bool(index.get("document_indexed")),
                "chunks_indexed": index.get("chunks_indexed"),
                "metadata_persisted": bool(index.get("metadata_persisted")),
                "idempotent": bool(index.get("idempotent")),
            },
        ),
    ]
    if document:
        records.append(
            _record(
                runtime_domain="knowledge_index",
                record_type="knowledge_document",
                record_key=str(document.get("knowledge_document_id")),
                artifact_id=_artifact_id(document, resolved_artifact_id),
                processing_session_id=processing_session_id,
                execution_status=str(document.get("status") or index.get("index_status") or "unknown"),
                payload=document,
                summary={
                    "knowledge_document_id": document.get("knowledge_document_id"),
                    "publication_id": document.get("publication_id"),
                    "version": document.get("version"),
                    "status": document.get("status"),
                },
            )
        )
    for chunk in _as_list(index.get("knowledge_chunks")):
        chunk_dict = _as_dict(chunk)
        records.append(
            _record(
                runtime_domain="knowledge_index",
                record_type="knowledge_chunk",
                record_key=str(chunk_dict.get("knowledge_chunk_id") or chunk_dict.get("published_chunk_id")),
                artifact_id=_artifact_id(chunk_dict, resolved_artifact_id),
                processing_session_id=processing_session_id,
                execution_status=str(chunk_dict.get("status") or index.get("index_status") or "unknown"),
                content_hash=chunk_dict.get("content_hash"),
                payload=chunk_dict,
                summary={
                    "knowledge_chunk_id": chunk_dict.get("knowledge_chunk_id"),
                    "published_chunk_id": chunk_dict.get("published_chunk_id"),
                    "chunk_index": chunk_dict.get("chunk_index"),
                    "semantic_hash": chunk_dict.get("semantic_hash"),
                },
            )
        )
    for metadata in _as_list(index.get("knowledge_metadata")):
        metadata_dict = _as_dict(metadata)
        records.append(
            _record(
                runtime_domain="knowledge_index",
                record_type="knowledge_metadata",
                record_key=str(
                    metadata_dict.get("knowledge_metadata_id")
                    or _stable_key(document.get("knowledge_document_id"), metadata_dict.get("metadata_key"))
                ),
                artifact_id=resolved_artifact_id,
                processing_session_id=processing_session_id,
                execution_status=str(index.get("index_status") or "unknown"),
                payload=metadata_dict,
                summary={
                    "metadata_key": metadata_dict.get("metadata_key"),
                    "knowledge_document_id": metadata_dict.get("knowledge_document_id"),
                },
            )
        )
    return records


def _search_records(search: dict[str, Any], *, artifact_id: str | None) -> list[RuntimePersistenceRecordDescriptor]:
    search_gateway = _as_dict(search.get("search_gateway"))
    search_session = _as_dict(search_gateway.get("search_session"))
    search_session_id = search.get("search_session_id") or search_session.get("search_session_id")
    records = [
        _record(
            runtime_domain="enterprise_search",
            record_type="search_session",
            record_key=str(
                search_session_id or _stable_key(search.get("normalized_query"), search.get("result_count"))
            ),
            artifact_id=artifact_id,
            execution_status=str(search.get("search_status") or "unknown"),
            payload=search_session or search_gateway,
            summary={
                "query": search.get("query") or search_session.get("query"),
                "normalized_query": search.get("normalized_query") or search_session.get("normalized_query"),
                "top_k": search_session.get("top_k"),
                "search_mode": search_session.get("search_mode"),
                "filters": search.get("filters")
                or (
                    search_session.get("search_config", {}).get("filters")
                    if isinstance(search_session.get("search_config"), dict)
                    else None
                ),
                "ranking_model": search.get("ranking_model"),
                "search_uses_postgresql_fts": bool(search.get("search_uses_postgresql_fts")),
                "semantic_search_used": bool(search.get("semantic_search_used")),
                "ai_required": bool(search.get("ai_required")),
            },
            validation=_as_dict(search.get("search_validation")),
            metrics={
                "total_count": search.get("total_count"),
                "result_count": search.get("result_count"),
                "citation_count": len(_as_list(search.get("citations"))),
            },
        ),
        _record(
            runtime_domain="enterprise_search",
            record_type="search_result_set",
            record_key=str(search_session_id or _stable_key(search.get("normalized_query"), "results")),
            artifact_id=artifact_id,
            execution_status=str(search.get("search_status") or "unknown"),
            payload=search,
            summary={
                "search_completed": bool(search.get("search_completed")),
                "normalized_query": search.get("normalized_query"),
                "total_count": search.get("total_count"),
                "result_count": search.get("result_count"),
                "ranking_model": search.get("ranking_model"),
                "search_uses_postgresql_fts": bool(search.get("search_uses_postgresql_fts")),
                "semantic_search_used": bool(search.get("semantic_search_used")),
                "ai_required": bool(search.get("ai_required")),
            },
            validation=_as_dict(search.get("search_validation")),
            metrics={
                "total_count": search.get("total_count"),
                "result_count": search.get("result_count"),
                "citation_count": len(_as_list(search.get("citations"))),
            },
        ),
    ]
    for result in _as_list(search.get("results")):
        result_dict = _as_dict(result)
        records.append(
            _record(
                runtime_domain="enterprise_search",
                record_type="search_result",
                record_key=str(
                    result_dict.get("search_result_id") or _stable_key(search_session_id, result_dict.get("rank"))
                ),
                artifact_id=_artifact_id(result_dict, artifact_id),
                execution_status=str(search.get("search_status") or "unknown"),
                content_hash=result_dict.get("content_hash"),
                payload=result_dict,
                summary={
                    "rank": result_dict.get("rank"),
                    "score": result_dict.get("score"),
                    "published_chunk_id": result_dict.get("published_chunk_id"),
                },
                metrics=_as_dict(result_dict.get("ranking_trace")),
            )
        )
    for citation in _as_list(search.get("citations")):
        citation_dict = _as_dict(citation)
        records.append(
            _record(
                runtime_domain="enterprise_search",
                record_type="citation",
                record_key=str(
                    citation_dict.get("citation_id")
                    or _stable_key(search_session_id, citation_dict.get("published_chunk_id"))
                ),
                artifact_id=_artifact_id(citation_dict, artifact_id),
                execution_status=str(search.get("search_status") or "unknown"),
                content_hash=citation_dict.get("content_hash"),
                payload=citation_dict,
                summary={
                    "citation_id": citation_dict.get("citation_id"),
                    "source": citation_dict.get("source"),
                    "published_chunk_id": citation_dict.get("published_chunk_id"),
                    "chunk_index": citation_dict.get("chunk_index"),
                },
            )
        )
    return records


def _knowledge_lifecycle_records(
    lifecycle: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    lifecycle_gateway = _as_dict(lifecycle.get("knowledge_lifecycle_gateway"))
    lifecycle_session = _as_dict(lifecycle_gateway.get("lifecycle_session"))
    lifecycle_run = _as_dict(lifecycle.get("lifecycle_run"))
    resolved_artifact_id = _artifact_id(lifecycle, _artifact_id(lifecycle_session, artifact_id))
    session_id = lifecycle_session.get("lifecycle_session_id") or lifecycle_run.get("lifecycle_session_id")
    operation = lifecycle.get("operation") or lifecycle_session.get("operation")
    mode = lifecycle.get("mode") or lifecycle_session.get("mode")
    records = [
        _record(
            runtime_domain="knowledge_lifecycle",
            record_type="lifecycle_session",
            record_key=str(session_id or _stable_key(operation, mode, resolved_artifact_id)),
            artifact_id=resolved_artifact_id,
            execution_status=str(lifecycle.get("lifecycle_status") or "unknown"),
            payload=lifecycle_session or lifecycle_gateway,
            summary={
                "operation": operation,
                "mode": mode,
                "artifact_id": lifecycle_session.get("artifact_id"),
                "publication_id": lifecycle_session.get("publication_id"),
            },
        ),
        _record(
            runtime_domain="knowledge_lifecycle",
            record_type="lifecycle_result",
            record_key=str(lifecycle_run.get("knowledge_lifecycle_run_id") or _stable_key(session_id, operation, mode)),
            artifact_id=resolved_artifact_id,
            execution_status=str(lifecycle.get("lifecycle_status") or "unknown"),
            payload=lifecycle,
            summary={
                "operation": operation,
                "mode": mode,
                "decision": lifecycle.get("decision"),
                "lifecycle_completed": bool(lifecycle.get("lifecycle_completed")),
                "documents_updated": lifecycle.get("documents_updated"),
                "chunks_updated": lifecycle.get("chunks_updated"),
                "documents_deleted": lifecycle.get("documents_deleted"),
                "chunks_deleted": lifecycle.get("chunks_deleted"),
            },
            validation={
                "blocking_issues": lifecycle.get("blocking_issues") or [],
                "warnings": lifecycle.get("warnings") or [],
            },
            metrics=_as_dict(lifecycle.get("health")),
        ),
    ]
    if lifecycle.get("health"):
        records.append(
            _record(
                runtime_domain="knowledge_lifecycle",
                record_type="index_health",
                record_key=str(_stable_key(lifecycle_run.get("knowledge_lifecycle_run_id"), "health")),
                artifact_id=resolved_artifact_id,
                execution_status=str(lifecycle.get("lifecycle_status") or "unknown"),
                payload=_as_dict(lifecycle.get("health")),
                summary=_as_dict(lifecycle.get("health")),
                metrics=_as_dict(lifecycle.get("statistics")),
            )
        )
    return records


def _knowledge_fts_records(fts: dict[str, Any], *, artifact_id: str | None) -> list[RuntimePersistenceRecordDescriptor]:
    fts_gateway = _as_dict(fts.get("knowledge_fts_gateway"))
    fts_session = _as_dict(fts_gateway.get("fts_session"))
    session_id = fts.get("fts_session_id") or fts_session.get("fts_session_id")
    result_artifact_id = artifact_id
    results = _as_list(fts.get("results"))
    if result_artifact_id is None and results:
        result_artifact_id = _artifact_id(_as_dict(results[0]), artifact_id)
    records = [
        _record(
            runtime_domain="knowledge_fts",
            record_type="fts_session",
            record_key=str(session_id or _stable_key(fts.get("normalized_query"), fts.get("result_count"))),
            artifact_id=result_artifact_id,
            execution_status=str(fts.get("fts_search_status") or "unknown"),
            payload=fts_session or fts_gateway,
            summary={
                "query": fts.get("query") or fts_session.get("query"),
                "normalized_query": fts.get("normalized_query") or fts_session.get("normalized_query"),
                "top_k": fts_session.get("top_k"),
                "fts_config": fts.get("fts_projection", {}).get("fts_config")
                if isinstance(fts.get("fts_projection"), dict)
                else None,
            },
            validation=_as_dict(fts.get("fts_validation")),
        ),
        _record(
            runtime_domain="knowledge_fts",
            record_type="fts_result_set",
            record_key=str(session_id or _stable_key(fts.get("normalized_query"), "fts-results")),
            artifact_id=result_artifact_id,
            execution_status=str(fts.get("fts_search_status") or "unknown"),
            payload=fts,
            summary={
                "fts_search_completed": bool(fts.get("fts_search_completed")),
                "fts_search_succeeded": bool(fts.get("fts_search_succeeded")),
                "result_count": fts.get("result_count"),
                "search_uses_postgresql_fts": bool(fts.get("search_uses_postgresql_fts")),
            },
            validation=_as_dict(fts.get("fts_validation")),
            metrics=_as_dict(fts.get("fts_projection")),
        ),
    ]
    for result in results:
        result_dict = _as_dict(result)
        records.append(
            _record(
                runtime_domain="knowledge_fts",
                record_type="fts_result",
                record_key=str(result_dict.get("search_result_id") or _stable_key(session_id, result_dict.get("rank"))),
                artifact_id=_artifact_id(result_dict, result_artifact_id),
                execution_status=str(fts.get("fts_search_status") or "unknown"),
                content_hash=result_dict.get("content_hash"),
                payload=result_dict,
                summary={
                    "rank": result_dict.get("rank"),
                    "score": result_dict.get("score"),
                    "knowledge_chunk_id": result_dict.get("knowledge_chunk_id"),
                    "chunk_index": result_dict.get("chunk_index"),
                },
                metrics=_as_dict(result_dict.get("ranking_trace")),
            )
        )
    for citation in _as_list(fts.get("citations")):
        citation_dict = _as_dict(citation)
        records.append(
            _record(
                runtime_domain="knowledge_fts",
                record_type="fts_citation",
                record_key=str(
                    citation_dict.get("citation_id") or _stable_key(session_id, citation_dict.get("knowledge_chunk_id"))
                ),
                artifact_id=_artifact_id(citation_dict, result_artifact_id),
                execution_status=str(fts.get("fts_search_status") or "unknown"),
                content_hash=citation_dict.get("content_hash"),
                payload=citation_dict,
                summary={
                    "source": citation_dict.get("source"),
                    "knowledge_chunk_id": citation_dict.get("knowledge_chunk_id"),
                    "chunk_index": citation_dict.get("chunk_index"),
                },
            )
        )
    return records


def _embedding_runtime_records(
    embedding: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    gateway = _as_dict(embedding.get("embedding_gateway"))
    session = _as_dict(gateway.get("embedding_session"))
    record = _as_dict(embedding.get("embedding_record"))
    metadata_execution = _as_dict(embedding.get("embedding_metadata_execution"))
    runtime_metadata = _as_dict(record.get("runtime_metadata"))
    knowledge_chunk = _as_dict(runtime_metadata.get("knowledge_chunk") or gateway.get("knowledge_chunk"))
    provider_descriptor = _as_dict(runtime_metadata.get("provider_descriptor"))
    provider_name = (
        record.get("provider_name")
        or provider_descriptor.get("provider_name")
        or metadata_execution.get("provider_name")
    )
    provider_type = provider_descriptor.get("provider_type") or metadata_execution.get("provider_type")
    provider_version = provider_descriptor.get("provider_version") or metadata_execution.get("provider_version")
    resolved_artifact_id = _artifact_id(knowledge_chunk, artifact_id)
    embedding_id = record.get("embedding_id")
    chunk_id = record.get("chunk_id") or session.get("chunk_id") or metadata_execution.get("chunk_id")
    records = [
        _record(
            runtime_domain="embedding_runtime",
            record_type="embedding_session",
            record_key=str(
                session.get("embedding_session_id")
                or _stable_key(chunk_id, session.get("model_name"), session.get("model_version"))
            ),
            artifact_id=resolved_artifact_id,
            provider=str(provider_name or record.get("model_name") or session.get("model_name") or "metadata-only"),
            execution_status=str(embedding.get("embedding_status") or "unknown"),
            content_hash=knowledge_chunk.get("content_hash"),
            payload=session or gateway,
            summary={
                "chunk_id": chunk_id,
                "model_name": record.get("model_name") or session.get("model_name"),
                "model_version": record.get("model_version") or session.get("model_version"),
                "provider_name": provider_name,
                "provider_type": provider_type,
                "provider_version": provider_version,
                "embedding_dimensions": record.get("embedding_dimensions") or session.get("embedding_dimensions"),
                "embedding_runtime_prepared": bool(embedding.get("embedding_runtime_prepared")),
            },
            validation={
                "blocking_issues": embedding.get("blocking_issues") or [],
                "warnings": embedding.get("warnings") or [],
            },
        )
    ]
    if record:
        records.append(
            _record(
                runtime_domain="embedding_runtime",
                record_type="embedding_record",
                record_key=str(
                    embedding_id or _stable_key(chunk_id, record.get("model_name"), record.get("model_version"))
                ),
                artifact_id=resolved_artifact_id,
                provider=str(provider_name or "metadata-only"),
                execution_status=str(record.get("embedding_status") or embedding.get("embedding_status") or "unknown"),
                content_hash=record.get("embedding_hash") or knowledge_chunk.get("content_hash"),
                payload=record,
                summary={
                    "embedding_id": embedding_id,
                    "chunk_id": chunk_id,
                    "model_name": record.get("model_name"),
                    "model_version": record.get("model_version"),
                    "provider_name": provider_name,
                    "provider_type": provider_type,
                    "provider_version": provider_version,
                    "embedding_dimensions": record.get("embedding_dimensions"),
                    "embedding_metadata_persisted": bool(embedding.get("embedding_metadata_persisted")),
                    "embedding_vector_generated": False,
                    "embedding_provider_called": False,
                    "postgresql_source_of_truth": True,
                },
                metrics={
                    "semantic_search_used": False,
                    "qdrant_indexed": False,
                    "qdrant_index_derived": True,
                },
            )
        )
    return records


def _vector_index_runtime_records(
    vector_index: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    gateway = _as_dict(vector_index.get("vector_index_gateway"))
    session = _as_dict(gateway.get("vector_index_session"))
    record = _as_dict(vector_index.get("vector_index_record"))
    metadata_execution = _as_dict(vector_index.get("vector_index_metadata_execution"))
    runtime_metadata = _as_dict(record.get("runtime_metadata"))
    knowledge_chunk = _as_dict(runtime_metadata.get("knowledge_chunk") or gateway.get("knowledge_chunk"))
    qdrant_provider_name = runtime_metadata.get("qdrant_provider_name") or vector_index.get("qdrant_provider_name")
    qdrant_provider_type = runtime_metadata.get("qdrant_provider_type") or vector_index.get("qdrant_provider_type")
    qdrant_enabled = bool(runtime_metadata.get("qdrant_enabled") or vector_index.get("qdrant_enabled"))
    qdrant_descriptor_only = bool(
        runtime_metadata.get("qdrant_descriptor_only", vector_index.get("qdrant_descriptor_only", True))
    )
    resolved_artifact_id = _artifact_id(knowledge_chunk, artifact_id)
    vector_index_id = record.get("vector_index_id")
    embedding_id = record.get("embedding_id") or metadata_execution.get("embedding_id") or session.get("embedding_id")
    records = [
        _record(
            runtime_domain="vector_index_runtime",
            record_type="vector_index_session",
            record_key=str(
                session.get("vector_index_session_id")
                or _stable_key(embedding_id, session.get("index_name"), session.get("index_provider"))
            ),
            artifact_id=resolved_artifact_id,
            provider=str(record.get("index_provider") or session.get("index_provider") or "qdrant-disabled"),
            execution_status=str(vector_index.get("vector_index_status") or "unknown"),
            content_hash=record.get("vector_hash") or knowledge_chunk.get("content_hash"),
            payload=session or gateway,
            summary={
                "embedding_id": embedding_id,
                "knowledge_chunk_id": record.get("knowledge_chunk_id") or metadata_execution.get("knowledge_chunk_id"),
                "index_provider": record.get("index_provider") or session.get("index_provider"),
                "index_provider_type": record.get("index_provider_type") or session.get("index_provider_type"),
                "index_status": record.get("index_status") or vector_index.get("vector_index_status"),
                "qdrant_provider_name": qdrant_provider_name,
                "qdrant_provider_type": qdrant_provider_type,
                "qdrant_enabled": qdrant_enabled,
                "qdrant_descriptor_only": qdrant_descriptor_only,
                "vector_values_stored": False,
                "qdrant_called": False,
                "network_call_attempted": False,
                "semantic_search_enabled": False,
                "hybrid_search_enabled": False,
            },
            validation={
                "blocking_issues": vector_index.get("blocking_issues") or [],
                "warnings": vector_index.get("warnings") or [],
            },
        )
    ]
    if record:
        records.append(
            _record(
                runtime_domain="vector_index_runtime",
                record_type="vector_index_record",
                record_key=str(
                    vector_index_id or _stable_key(embedding_id, record.get("index_name"), record.get("index_provider"))
                ),
                artifact_id=resolved_artifact_id,
                provider=str(record.get("index_provider") or "qdrant-disabled"),
                execution_status=str(
                    record.get("index_status") or vector_index.get("vector_index_status") or "unknown"
                ),
                content_hash=record.get("vector_hash") or knowledge_chunk.get("content_hash"),
                payload=record,
                summary={
                    "vector_index_id": vector_index_id,
                    "embedding_id": embedding_id,
                    "knowledge_chunk_id": record.get("knowledge_chunk_id"),
                    "index_provider": record.get("index_provider"),
                    "index_provider_type": record.get("index_provider_type"),
                    "index_status": record.get("index_status"),
                    "qdrant_provider_name": qdrant_provider_name,
                    "qdrant_provider_type": qdrant_provider_type,
                    "qdrant_enabled": qdrant_enabled,
                    "qdrant_descriptor_only": qdrant_descriptor_only,
                    "vector_values_stored": False,
                    "qdrant_called": False,
                    "network_call_attempted": False,
                    "semantic_search_enabled": False,
                    "hybrid_search_enabled": False,
                    "postgresql_source_of_truth": True,
                },
                metrics={
                    "vector_dimensions": record.get("vector_dimensions"),
                    "external_index_authoritative": False,
                },
            )
        )
    return records


def _semantic_search_runtime_records(
    semantic_search: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    gateway = _as_dict(semantic_search.get("semantic_search_gateway"))
    session = _as_dict(gateway.get("semantic_search_session"))
    plan = _as_dict(semantic_search.get("semantic_search_execution_plan"))
    result = _as_dict(semantic_search.get("semantic_search_result"))
    query = semantic_search.get("query") or session.get("query")
    normalized_query = semantic_search.get("normalized_query") or session.get("normalized_query")
    session_id = session.get("semantic_search_session_id") or _as_dict(plan.get("session")).get(
        "semantic_search_session_id"
    )
    provider_descriptor = _as_dict(session.get("qdrant_provider_descriptor"))
    return [
        _record(
            runtime_domain="semantic_search_runtime",
            record_type="semantic_search_session",
            record_key=str(session_id or _stable_key(normalized_query, "semantic-search-session")),
            artifact_id=artifact_id,
            provider=str(provider_descriptor.get("provider_name") or "qdrant-disabled"),
            execution_status=str(
                semantic_search.get("semantic_search_status") or result.get("semantic_search_status") or "prepared"
            ),
            payload=session or gateway,
            summary={
                "query": query,
                "normalized_query": normalized_query,
                "vector_index_id": semantic_search.get("vector_index_id") or session.get("vector_index_id"),
                "qdrant_provider_name": provider_descriptor.get("provider_name"),
                "qdrant_provider_type": provider_descriptor.get("provider_type"),
                "semantic_search_enabled": False,
                "semantic_search_executed": False,
                "vector_search_executed": False,
                "qdrant_called": False,
                "network_call_attempted": False,
                "hybrid_search_enabled": False,
                "postgresql_source_of_truth": True,
            },
            validation={
                "blocking_issues": semantic_search.get("blocking_issues") or [],
                "warnings": semantic_search.get("warnings") or [],
            },
        ),
        _record(
            runtime_domain="semantic_search_runtime",
            record_type="semantic_search_result",
            record_key=str(session_id or _stable_key(normalized_query, "semantic-search-result")),
            artifact_id=artifact_id,
            provider=str(provider_descriptor.get("provider_name") or "qdrant-disabled"),
            execution_status=str(result.get("semantic_search_status") or "prepared"),
            payload=semantic_search,
            summary={
                "query": query,
                "normalized_query": normalized_query,
                "semantic_search_runtime_prepared": bool(semantic_search.get("semantic_search_runtime_prepared")),
                "semantic_search_enabled": False,
                "semantic_search_executed": False,
                "vector_search_executed": False,
                "qdrant_called": False,
                "network_call_attempted": False,
                "hybrid_search_enabled": False,
                "enterprise_search_uses_postgresql_fts": True,
                "postgresql_source_of_truth": True,
            },
            metrics={
                "result_count": result.get("result_count", 0),
                "descriptor_only": True,
            },
        ),
    ]


def _hybrid_search_runtime_records(
    hybrid_search: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    gateway = _as_dict(hybrid_search.get("hybrid_search_gateway"))
    session = _as_dict(gateway.get("hybrid_search_session"))
    plan = _as_dict(hybrid_search.get("hybrid_search_execution_plan"))
    result = _as_dict(hybrid_search.get("hybrid_search_result"))
    query = hybrid_search.get("query") or session.get("query")
    normalized_query = hybrid_search.get("normalized_query") or session.get("normalized_query")
    session_id = session.get("hybrid_search_session_id") or _as_dict(plan.get("session")).get(
        "hybrid_search_session_id"
    )
    summary = {
        "query": query,
        "normalized_query": normalized_query,
        "hybrid_search_enabled": False,
        "hybrid_search_executed": False,
        "lexical_search_available": True,
        "lexical_search_source": "postgresql_fts",
        "semantic_search_available": True,
        "semantic_search_executed": False,
        "vector_search_executed": False,
        "qdrant_called": False,
        "reranking_executed": False,
        "llm_used": False,
        "assistant_used": False,
        "enterprise_search_uses_postgresql_fts": True,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="hybrid_search_runtime",
            record_type="hybrid_search_session",
            record_key=str(session_id or _stable_key(normalized_query, "hybrid-search-session")),
            artifact_id=artifact_id,
            provider="postgresql_fts",
            execution_status=str(
                hybrid_search.get("hybrid_search_status") or result.get("hybrid_search_status") or "prepared"
            ),
            payload=session or gateway,
            summary=summary,
            validation={
                "blocking_issues": hybrid_search.get("blocking_issues") or [],
                "warnings": hybrid_search.get("warnings") or [],
            },
        ),
        _record(
            runtime_domain="hybrid_search_runtime",
            record_type="hybrid_search_result",
            record_key=str(session_id or _stable_key(normalized_query, "hybrid-search-result")),
            artifact_id=artifact_id,
            provider="postgresql_fts",
            execution_status=str(result.get("hybrid_search_status") or "prepared"),
            payload=hybrid_search,
            summary={
                **summary,
                "hybrid_search_runtime_prepared": bool(hybrid_search.get("hybrid_search_runtime_prepared")),
                "enterprise_search_still_uses_postgresql_fts": bool(
                    hybrid_search.get("enterprise_search_still_uses_postgresql_fts")
                ),
            },
            metrics={
                "result_count": result.get("result_count", 0),
                "descriptor_only": True,
            },
        ),
    ]


def _workflow_runtime_records(
    workflow_runtime: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    workflow = _as_dict(workflow_runtime.get("workflow"))
    run = _as_dict(workflow_runtime.get("workflow_run"))
    plan = _as_dict(workflow_runtime.get("workflow_execution_plan"))
    workflow_id = workflow_runtime.get("workflow_id") or workflow.get("workflow_id")
    workflow_run_id = workflow_runtime.get("workflow_run_id") or run.get("workflow_run_id")
    step_count = (
        workflow_runtime.get("step_count")
        if workflow_runtime.get("step_count") is not None
        else len(_as_list(workflow_runtime.get("workflow_steps")))
    )
    summary = {
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "workflow_status": workflow_runtime.get("workflow_status") or workflow.get("workflow_status"),
        "run_status": workflow_runtime.get("run_status") or run.get("run_status"),
        "step_count": step_count,
        "workflow_executed": False,
        "external_action_called": False,
        "ai_used": False,
        "llm_used": False,
        "assistant_used": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="workflow_runtime",
            record_type="workflow_definition",
            record_key=str(workflow_id or _stable_key(workflow.get("workflow_key"), workflow.get("workflow_version"))),
            artifact_id=artifact_id,
            provider="workflow_runtime",
            execution_status=str(
                workflow.get("workflow_status") or workflow_runtime.get("workflow_status") or "prepared"
            ),
            payload=workflow or workflow_runtime,
            summary={
                **summary,
                "workflow_definition_created": bool(workflow_runtime.get("workflow_definition_created")),
                "workflow_steps_created": bool(workflow_runtime.get("workflow_steps_created")),
            },
            validation={
                "blocking_issues": workflow_runtime.get("blocking_issues") or [],
                "warnings": workflow_runtime.get("warnings") or [],
            },
        ),
        _record(
            runtime_domain="workflow_runtime",
            record_type="workflow_run",
            record_key=str(workflow_run_id or _stable_key(workflow_id, "workflow-run")),
            artifact_id=artifact_id,
            provider="workflow_runtime",
            execution_status=str(run.get("run_status") or workflow_runtime.get("run_status") or "planned"),
            payload=workflow_runtime,
            summary={
                **summary,
                "workflow_runtime_prepared": bool(workflow_runtime.get("workflow_runtime_prepared")),
                "workflow_run_created": bool(workflow_runtime.get("workflow_run_created")),
                "workflow_execution_planned": bool(workflow_runtime.get("workflow_execution_planned")),
            },
            metrics={
                "descriptor_only": True,
                "execution_allowed": bool(plan.get("execution_allowed")),
            },
        ),
    ]


def _assistant_runtime_records(
    assistant_runtime: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    assistant = _as_dict(assistant_runtime.get("assistant"))
    session = _as_dict(assistant_runtime.get("assistant_session"))
    run = _as_dict(assistant_runtime.get("assistant_run"))
    plan = _as_dict(assistant_runtime.get("assistant_runtime_plan"))
    assistant_id = assistant_runtime.get("assistant_id") or assistant.get("assistant_id")
    assistant_session_id = assistant_runtime.get("assistant_session_id") or session.get("assistant_session_id")
    assistant_run_id = assistant_runtime.get("assistant_run_id") or run.get("assistant_run_id")
    summary = {
        "assistant_id": assistant_id,
        "assistant_session_id": assistant_session_id,
        "assistant_run_id": assistant_run_id,
        "assistant_status": assistant_runtime.get("assistant_status") or assistant.get("assistant_status"),
        "session_status": assistant_runtime.get("session_status") or session.get("session_status"),
        "run_status": assistant_runtime.get("run_status") or run.get("run_status"),
        "selected_search_mode": assistant_runtime.get("selected_search_mode") or run.get("selected_search_mode"),
        "selected_runtime_domain": assistant_runtime.get("selected_runtime_domain")
        or run.get("selected_runtime_domain"),
        "assistant_executed": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_runtime",
            record_type="assistant_definition",
            record_key=str(
                assistant_id or _stable_key(assistant.get("assistant_key"), assistant.get("assistant_version"))
            ),
            artifact_id=artifact_id,
            provider="assistant_runtime",
            execution_status=str(
                assistant.get("assistant_status") or assistant_runtime.get("assistant_status") or "prepared"
            ),
            payload=assistant or assistant_runtime,
            summary={
                **summary,
                "assistant_definition_created": bool(assistant_runtime.get("assistant_definition_created")),
                "assistant_execution_planned": bool(assistant_runtime.get("assistant_execution_planned")),
            },
            validation={
                "blocking_issues": assistant_runtime.get("blocking_issues") or [],
                "warnings": assistant_runtime.get("warnings") or [],
            },
        ),
        _record(
            runtime_domain="assistant_runtime",
            record_type="assistant_run",
            record_key=str(assistant_run_id or _stable_key(assistant_id, assistant_session_id, "assistant-run")),
            artifact_id=artifact_id,
            provider="assistant_runtime",
            execution_status=str(run.get("run_status") or assistant_runtime.get("run_status") or "planned"),
            payload=assistant_runtime,
            summary={
                **summary,
                "assistant_runtime_prepared": bool(assistant_runtime.get("assistant_runtime_prepared")),
                "assistant_session_created": bool(assistant_runtime.get("assistant_session_created")),
                "assistant_run_created": bool(assistant_runtime.get("assistant_run_created")),
            },
            metrics={
                "descriptor_only": True,
                "execution_allowed": bool(plan.get("execution_allowed")),
            },
        ),
    ]


def _assistant_retrieval_runtime_records(
    assistant_retrieval_runtime: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    assistant = _as_dict(assistant_retrieval_runtime.get("assistant"))
    session = _as_dict(assistant_retrieval_runtime.get("assistant_session"))
    plan = _as_dict(assistant_retrieval_runtime.get("assistant_retrieval_plan"))
    runtime_plan = _as_dict(assistant_retrieval_runtime.get("assistant_retrieval_runtime_plan"))
    assistant_id = assistant_retrieval_runtime.get("assistant_id") or assistant.get("assistant_id")
    assistant_session_id = assistant_retrieval_runtime.get("assistant_session_id") or session.get(
        "assistant_session_id"
    )
    retrieval_plan_id = assistant_retrieval_runtime.get("retrieval_plan_id") or plan.get("retrieval_plan_id")
    summary = {
        "assistant_id": assistant_id,
        "assistant_session_id": assistant_session_id,
        "retrieval_plan_id": retrieval_plan_id,
        "plan_status": assistant_retrieval_runtime.get("plan_status") or plan.get("plan_status"),
        "execution_state": assistant_retrieval_runtime.get("execution_state") or plan.get("execution_state"),
        "selected_search_mode": assistant_retrieval_runtime.get("selected_search_mode")
        or plan.get("selected_search_mode"),
        "selected_runtime_domain": assistant_retrieval_runtime.get("selected_runtime_domain")
        or plan.get("selected_runtime_domain"),
        "enterprise_search_planned": bool(
            assistant_retrieval_runtime.get("enterprise_search_planned") or plan.get("enterprise_search_planned")
        ),
        "hybrid_search_planned": bool(
            assistant_retrieval_runtime.get("hybrid_search_planned") or plan.get("hybrid_search_planned")
        ),
        "semantic_search_planned": bool(
            assistant_retrieval_runtime.get("semantic_search_planned") or plan.get("semantic_search_planned")
        ),
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_retrieval_runtime",
            record_type="retrieval_plan",
            record_key=str(
                retrieval_plan_id or _stable_key(assistant_id, assistant_session_id, "assistant-retrieval-plan")
            ),
            artifact_id=artifact_id,
            provider="assistant_retrieval_runtime",
            execution_status=str(
                plan.get("plan_status") or assistant_retrieval_runtime.get("plan_status") or "planned"
            ),
            payload=assistant_retrieval_runtime,
            summary={
                **summary,
                "assistant_retrieval_runtime_prepared": bool(
                    assistant_retrieval_runtime.get("assistant_retrieval_runtime_prepared")
                ),
                "retrieval_plan_created": bool(assistant_retrieval_runtime.get("retrieval_plan_created")),
            },
            validation={
                "blocking_issues": assistant_retrieval_runtime.get("blocking_issues") or [],
                "warnings": assistant_retrieval_runtime.get("warnings") or [],
            },
            metrics={
                "descriptor_only": True,
                "execution_allowed": bool(runtime_plan.get("execution_allowed")),
            },
        )
    ]


def _assistant_retrieval_execution_readiness_records(
    assistant_retrieval_execution_readiness: dict[str, Any],
    *,
    artifact_id: str | None,
) -> list[RuntimePersistenceRecordDescriptor]:
    execution_plan = _as_dict(assistant_retrieval_execution_readiness.get("assistant_retrieval_execution_plan"))
    runtime_plan = _as_dict(assistant_retrieval_execution_readiness.get("assistant_retrieval_execution_runtime_plan"))
    execution_plan_id = assistant_retrieval_execution_readiness.get("execution_plan_id") or execution_plan.get(
        "execution_plan_id"
    )
    retrieval_plan_id = assistant_retrieval_execution_readiness.get("retrieval_plan_id") or execution_plan.get(
        "retrieval_plan_id"
    )
    summary = {
        "execution_plan_id": execution_plan_id,
        "retrieval_plan_id": retrieval_plan_id,
        "assistant_id": assistant_retrieval_execution_readiness.get("assistant_id")
        or execution_plan.get("assistant_id"),
        "assistant_session_id": assistant_retrieval_execution_readiness.get("assistant_session_id")
        or execution_plan.get("assistant_session_id"),
        "execution_status": assistant_retrieval_execution_readiness.get("execution_status")
        or execution_plan.get("execution_status"),
        "execution_state": assistant_retrieval_execution_readiness.get("execution_state")
        or execution_plan.get("execution_state"),
        "selected_search_mode": assistant_retrieval_execution_readiness.get("selected_search_mode")
        or execution_plan.get("selected_search_mode"),
        "selected_runtime_domain": assistant_retrieval_execution_readiness.get("selected_runtime_domain")
        or execution_plan.get("selected_runtime_domain"),
        "enterprise_search_execution_prepared": bool(
            assistant_retrieval_execution_readiness.get("enterprise_search_execution_prepared")
            or execution_plan.get("enterprise_search_execution_prepared")
        ),
        "semantic_search_execution_prepared": bool(
            assistant_retrieval_execution_readiness.get("semantic_search_execution_prepared")
            or execution_plan.get("semantic_search_execution_prepared")
        ),
        "hybrid_search_execution_prepared": bool(
            assistant_retrieval_execution_readiness.get("hybrid_search_execution_prepared")
            or execution_plan.get("hybrid_search_execution_prepared")
        ),
        "retrieval_executed": False,
        "answer_generated": False,
        "llm_used": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_retrieval_execution_readiness",
            record_type="execution_readiness",
            record_key=str(
                execution_plan_id or _stable_key(retrieval_plan_id, "assistant-retrieval-execution-readiness")
            ),
            artifact_id=artifact_id,
            provider="assistant_retrieval_execution_readiness",
            execution_status=str(
                execution_plan.get("execution_status")
                or assistant_retrieval_execution_readiness.get("execution_status")
                or "prepared"
            ),
            payload=assistant_retrieval_execution_readiness,
            summary={
                **summary,
                "assistant_retrieval_execution_readiness_prepared": bool(
                    assistant_retrieval_execution_readiness.get("assistant_retrieval_execution_readiness_prepared")
                ),
                "execution_readiness_created": bool(
                    assistant_retrieval_execution_readiness.get("execution_readiness_created")
                ),
            },
            validation={
                "blocking_issues": assistant_retrieval_execution_readiness.get("blocking_issues") or [],
                "warnings": assistant_retrieval_execution_readiness.get("warnings") or [],
            },
            metrics={
                "descriptor_only": True,
                "execution_allowed": bool(runtime_plan.get("execution_allowed")),
            },
        )
    ]


def _assistant_search_execution_records(
    assistant_search_execution: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    search_execution = _as_dict(assistant_search_execution.get("assistant_search_execution"))
    enterprise_search = _as_dict(assistant_search_execution.get("enterprise_search"))
    search_execution_id = assistant_search_execution.get("search_execution_id") or search_execution.get(
        "search_execution_id"
    )
    result_count = int(
        assistant_search_execution.get("result_count")
        or search_execution.get("result_count")
        or enterprise_search.get("result_count")
        or 0
    )
    summary = {
        "search_execution_id": search_execution_id,
        "execution_plan_id": assistant_search_execution.get("execution_plan_id")
        or search_execution.get("execution_plan_id"),
        "retrieval_plan_id": assistant_search_execution.get("retrieval_plan_id")
        or search_execution.get("retrieval_plan_id"),
        "assistant_id": assistant_search_execution.get("assistant_id") or search_execution.get("assistant_id"),
        "assistant_session_id": assistant_search_execution.get("assistant_session_id")
        or search_execution.get("assistant_session_id"),
        "search_query": assistant_search_execution.get("search_query") or search_execution.get("search_query"),
        "selected_search_mode": assistant_search_execution.get("selected_search_mode")
        or search_execution.get("search_mode"),
        "selected_runtime_domain": assistant_search_execution.get("selected_runtime_domain")
        or search_execution.get("runtime_domain"),
        "search_completed": bool(
            assistant_search_execution.get("search_completed") or search_execution.get("search_completed")
        ),
        "enterprise_search_executed": bool(
            assistant_search_execution.get("enterprise_search_executed")
            or search_execution.get("enterprise_search_executed")
        ),
        "search_duration_ms": assistant_search_execution.get("search_duration_ms")
        or search_execution.get("search_duration_ms"),
        "result_count": result_count,
        "result_count_gt_zero": result_count > 0,
        "lexical_search_used": bool(
            assistant_search_execution.get("lexical_search_used") or search_execution.get("lexical_search_used")
        ),
        "postgresql_fts_used": bool(
            assistant_search_execution.get("postgresql_fts_used") or search_execution.get("postgresql_fts_used")
        ),
        "semantic_search_used": False,
        "hybrid_search_used": False,
        "qdrant_used": False,
        "reranking_used": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_search_execution",
            record_type="search_execution",
            record_key=str(
                search_execution_id
                or _stable_key(
                    summary.get("execution_plan_id"), summary.get("search_query"), "assistant-search-execution"
                )
            ),
            artifact_id=artifact_id,
            provider="assistant_search_execution",
            execution_status="completed" if summary["search_completed"] else "failed",
            payload=assistant_search_execution,
            summary=summary,
            validation={
                "blocking_issues": assistant_search_execution.get("blocking_issues") or [],
                "warnings": assistant_search_execution.get("warnings") or [],
            },
            metrics={
                "search_duration_ms": summary.get("search_duration_ms"),
                "result_count": result_count,
            },
        )
    ]


def _assistant_context_builder_records(
    assistant_context_builder: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    context_package = _as_dict(assistant_context_builder.get("assistant_context_package"))
    context_package_id = assistant_context_builder.get("context_package_id") or context_package.get(
        "context_package_id"
    )
    chunk_count = int(assistant_context_builder.get("chunk_count") or context_package.get("chunk_count") or 0)
    citation_count = int(assistant_context_builder.get("citation_count") or context_package.get("citation_count") or 0)
    summary = {
        "context_package_id": context_package_id,
        "search_execution_id": assistant_context_builder.get("search_execution_id")
        or context_package.get("search_execution_id"),
        "assistant_id": assistant_context_builder.get("assistant_id") or context_package.get("assistant_id"),
        "assistant_session_id": assistant_context_builder.get("assistant_session_id")
        or context_package.get("assistant_session_id"),
        "package_status": context_package.get("package_status"),
        "chunk_count": chunk_count,
        "citation_count": citation_count,
        "chunk_count_gt_zero": chunk_count > 0,
        "citation_count_gt_zero": citation_count > 0,
        "total_tokens_estimated": assistant_context_builder.get("total_tokens_estimated")
        or context_package.get("total_tokens_estimated"),
        "context_size_bytes": assistant_context_builder.get("context_size_bytes")
        or context_package.get("context_size_bytes"),
        "truncation_required": bool(
            assistant_context_builder.get("truncation_required") or context_package.get("truncation_required")
        ),
        "truncation_applied": bool(
            assistant_context_builder.get("truncation_applied") or context_package.get("truncation_applied")
        ),
        "ordered_context_created": bool(
            assistant_context_builder.get("ordered_context_created") or context_package.get("ordered_context_created")
        ),
        "ordered_citations_created": bool(
            assistant_context_builder.get("ordered_citations_created")
            or context_package.get("ordered_citations_created")
        ),
        "token_estimation_completed": bool(
            assistant_context_builder.get("token_estimation_completed")
            or context_package.get("token_estimation_completed")
        ),
        "llm_used": False,
        "answer_generated": False,
        "workflow_executed": False,
        "tool_called": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_context_builder",
            record_type="context_package",
            record_key=str(
                context_package_id or _stable_key(summary.get("search_execution_id"), "assistant-context-package")
            ),
            artifact_id=artifact_id,
            provider="assistant_context_builder",
            execution_status=str(context_package.get("package_status") or "created"),
            payload=assistant_context_builder,
            summary=summary,
            validation={
                "blocking_issues": assistant_context_builder.get("blocking_issues") or [],
                "warnings": assistant_context_builder.get("warnings") or [],
            },
            metrics={
                "chunk_count": chunk_count,
                "citation_count": citation_count,
                "total_tokens_estimated": summary.get("total_tokens_estimated"),
                "context_size_bytes": summary.get("context_size_bytes"),
            },
        )
    ]


def _assistant_prompt_assembly_records(
    assistant_prompt_assembly: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    prompt_package = _as_dict(assistant_prompt_assembly.get("assistant_prompt_package"))
    prompt_package_id = assistant_prompt_assembly.get("prompt_package_id") or prompt_package.get("prompt_package_id")
    summary = {
        "prompt_package_id": prompt_package_id,
        "context_package_id": assistant_prompt_assembly.get("context_package_id")
        or prompt_package.get("context_package_id"),
        "assistant_id": assistant_prompt_assembly.get("assistant_id") or prompt_package.get("assistant_id"),
        "assistant_session_id": assistant_prompt_assembly.get("assistant_session_id")
        or prompt_package.get("assistant_session_id"),
        "package_status": prompt_package.get("package_status"),
        "system_prompt_created": bool(
            assistant_prompt_assembly.get("system_prompt_created") or prompt_package.get("system_prompt_created")
        ),
        "assistant_instructions_created": bool(
            assistant_prompt_assembly.get("assistant_instructions_created")
            or prompt_package.get("assistant_instructions_created")
        ),
        "assembled_context_created": bool(
            assistant_prompt_assembly.get("assembled_context_created")
            or prompt_package.get("assembled_context_created")
        ),
        "citations_attached": bool(
            assistant_prompt_assembly.get("citations_attached") or prompt_package.get("citations_attached")
        ),
        "estimated_prompt_tokens": assistant_prompt_assembly.get("estimated_prompt_tokens")
        or prompt_package.get("estimated_prompt_tokens"),
        "prompt_size_bytes": assistant_prompt_assembly.get("prompt_size_bytes")
        or prompt_package.get("prompt_size_bytes"),
        "llm_ready": bool(assistant_prompt_assembly.get("llm_ready") or prompt_package.get("llm_ready")),
        "llm_invoked": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_prompt_assembly",
            record_type="prompt_package",
            record_key=str(
                prompt_package_id or _stable_key(summary.get("context_package_id"), "assistant-prompt-package")
            ),
            artifact_id=artifact_id,
            provider="assistant_prompt_assembly",
            execution_status=str(prompt_package.get("package_status") or "created"),
            payload=assistant_prompt_assembly,
            summary=summary,
            validation={
                "blocking_issues": assistant_prompt_assembly.get("blocking_issues") or [],
                "warnings": assistant_prompt_assembly.get("warnings") or [],
            },
            metrics={
                "estimated_prompt_tokens": summary.get("estimated_prompt_tokens"),
                "prompt_size_bytes": summary.get("prompt_size_bytes"),
            },
        )
    ]


def _assistant_llm_gateway_records(
    assistant_llm_gateway: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    llm_plan = _as_dict(assistant_llm_gateway.get("assistant_llm_invocation_plan"))
    gateway_id = assistant_llm_gateway.get("gateway_id") or llm_plan.get("gateway_id")
    summary = {
        "gateway_id": gateway_id,
        "prompt_package_id": assistant_llm_gateway.get("prompt_package_id") or llm_plan.get("prompt_package_id"),
        "assistant_id": assistant_llm_gateway.get("assistant_id") or llm_plan.get("assistant_id"),
        "assistant_session_id": assistant_llm_gateway.get("assistant_session_id")
        or llm_plan.get("assistant_session_id"),
        "provider_type": assistant_llm_gateway.get("provider_type") or llm_plan.get("provider_type"),
        "provider_name": assistant_llm_gateway.get("provider_name") or llm_plan.get("provider_name"),
        "model_name": assistant_llm_gateway.get("model_name") or llm_plan.get("model_name"),
        "provider_ready": bool(
            assistant_llm_gateway.get("provider_ready")
            if "provider_ready" in assistant_llm_gateway
            else llm_plan.get("provider_ready")
        ),
        "execution_allowed": bool(
            assistant_llm_gateway.get("execution_allowed")
            if "execution_allowed" in assistant_llm_gateway
            else llm_plan.get("execution_allowed")
        ),
        "blocked_reason": assistant_llm_gateway.get("blocked_reason") or llm_plan.get("blocked_reason"),
        "planned_temperature": assistant_llm_gateway.get("planned_temperature")
        if "planned_temperature" in assistant_llm_gateway
        else llm_plan.get("planned_temperature"),
        "planned_max_tokens": assistant_llm_gateway.get("planned_max_tokens") or llm_plan.get("planned_max_tokens"),
        "planned_top_p": assistant_llm_gateway.get("planned_top_p")
        if "planned_top_p" in assistant_llm_gateway
        else llm_plan.get("planned_top_p"),
        "planned_timeout": assistant_llm_gateway.get("planned_timeout") or llm_plan.get("planned_timeout"),
        "llm_invoked": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_llm_gateway",
            record_type="llm_invocation_plan",
            record_key=str(
                gateway_id or _stable_key(summary.get("prompt_package_id"), "assistant-llm-invocation-plan")
            ),
            artifact_id=artifact_id,
            provider="assistant_llm_gateway",
            execution_status="planned",
            payload=assistant_llm_gateway,
            summary=summary,
            validation={
                "blocking_issues": assistant_llm_gateway.get("blocking_issues") or [],
                "warnings": assistant_llm_gateway.get("warnings") or [],
            },
            metrics={
                "planned_temperature": summary.get("planned_temperature"),
                "planned_max_tokens": summary.get("planned_max_tokens"),
                "planned_top_p": summary.get("planned_top_p"),
                "planned_timeout": summary.get("planned_timeout"),
            },
        )
    ]


def _assistant_llm_execution_records(
    assistant_llm_execution: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    llm_execution = _as_dict(assistant_llm_execution.get("assistant_llm_execution"))
    llm_execution_id = assistant_llm_execution.get("llm_execution_id") or llm_execution.get("llm_execution_id")
    summary = {
        "llm_execution_id": llm_execution_id,
        "gateway_id": assistant_llm_execution.get("gateway_id") or llm_execution.get("gateway_id"),
        "prompt_package_id": assistant_llm_execution.get("prompt_package_id") or llm_execution.get("prompt_package_id"),
        "assistant_id": assistant_llm_execution.get("assistant_id") or llm_execution.get("assistant_id"),
        "assistant_session_id": assistant_llm_execution.get("assistant_session_id")
        or llm_execution.get("assistant_session_id"),
        "provider_type": assistant_llm_execution.get("provider_type") or llm_execution.get("provider_type"),
        "provider_name": assistant_llm_execution.get("provider_name") or llm_execution.get("provider_name"),
        "model_name": assistant_llm_execution.get("model_name") or llm_execution.get("model_name"),
        "execution_status": assistant_llm_execution.get("execution_status") or llm_execution.get("execution_status"),
        "execution_allowed": bool(
            assistant_llm_execution.get("execution_allowed")
            if "execution_allowed" in assistant_llm_execution
            else llm_execution.get("execution_allowed")
        ),
        "provider_called": bool(
            assistant_llm_execution.get("provider_called")
            if "provider_called" in assistant_llm_execution
            else llm_execution.get("provider_called")
        ),
        "provider_call_mode": assistant_llm_execution.get("provider_call_mode")
        or llm_execution.get("provider_call_mode"),
        "raw_output_created": bool(
            assistant_llm_execution.get("raw_output_created") or llm_execution.get("raw_output_created")
        ),
        "raw_output_persisted": bool(
            assistant_llm_execution.get("raw_output_persisted") or llm_execution.get("raw_output_persisted")
        ),
        "citation_verification_completed": False,
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_llm_execution",
            record_type="llm_execution",
            record_key=str(llm_execution_id or _stable_key(summary.get("gateway_id"), "assistant-llm-execution")),
            artifact_id=artifact_id,
            provider="assistant_llm_execution",
            execution_status=str(summary.get("execution_status") or "completed"),
            payload=assistant_llm_execution,
            summary=summary,
            validation={
                "blocking_issues": assistant_llm_execution.get("blocking_issues") or [],
                "warnings": assistant_llm_execution.get("warnings") or [],
            },
            metrics={
                "prompt_tokens_estimated": assistant_llm_execution.get("prompt_tokens_estimated")
                or llm_execution.get("prompt_tokens_estimated"),
                "completion_tokens_estimated": assistant_llm_execution.get("completion_tokens_estimated")
                or llm_execution.get("completion_tokens_estimated"),
                "total_tokens_estimated": assistant_llm_execution.get("total_tokens_estimated")
                or llm_execution.get("total_tokens_estimated"),
                "latency_ms": assistant_llm_execution.get("latency_ms")
                if "latency_ms" in assistant_llm_execution
                else llm_execution.get("latency_ms"),
            },
        )
    ]


def _assistant_citation_verification_records(
    assistant_citation_verification: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    verification = _as_dict(assistant_citation_verification.get("assistant_citation_verification"))
    citation_verification_id = (
        assistant_citation_verification.get("citation_verification_id")
        or assistant_citation_verification.get("id")
        or verification.get("citation_verification_id")
    )
    summary = {
        "citation_verification_id": citation_verification_id,
        "assistant_runtime_id": assistant_citation_verification.get("assistant_runtime_id")
        or verification.get("assistant_runtime_id"),
        "llm_execution_id": assistant_citation_verification.get("llm_execution_id")
        or verification.get("llm_execution_id"),
        "prompt_package_id": assistant_citation_verification.get("prompt_package_id")
        or verification.get("prompt_package_id"),
        "context_package_id": assistant_citation_verification.get("context_package_id")
        or verification.get("context_package_id"),
        "verification_status": assistant_citation_verification.get("verification_status")
        or verification.get("verification_status"),
        "citation_runtime_created": bool(
            assistant_citation_verification.get("citation_runtime_created")
            or verification.get("citation_runtime_created")
        ),
        "verification_completed": bool(
            assistant_citation_verification.get("verification_completed") or verification.get("verification_completed")
        ),
        "verified_citation_count": assistant_citation_verification.get("verified_citation_count")
        or verification.get("verified_citation_count"),
        "missing_citation_count": assistant_citation_verification.get("missing_citation_count")
        if "missing_citation_count" in assistant_citation_verification
        else verification.get("missing_citation_count"),
        "invalid_citation_count": assistant_citation_verification.get("invalid_citation_count")
        if "invalid_citation_count" in assistant_citation_verification
        else verification.get("invalid_citation_count"),
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_citation_verification",
            record_type="citation_verification",
            record_key=str(
                citation_verification_id
                or _stable_key(summary.get("llm_execution_id"), "assistant-citation-verification")
            ),
            artifact_id=artifact_id,
            provider="assistant_citation_verification",
            execution_status=str(summary.get("verification_status") or "completed"),
            payload=assistant_citation_verification,
            summary=summary,
            validation={
                "blocking_issues": assistant_citation_verification.get("blocking_issues") or [],
                "warnings": assistant_citation_verification.get("warnings") or [],
            },
            metrics={
                "verified_citation_count": summary.get("verified_citation_count"),
                "missing_citation_count": summary.get("missing_citation_count"),
                "invalid_citation_count": summary.get("invalid_citation_count"),
            },
        )
    ]


def _assistant_response_records(
    assistant_response: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    response = _as_dict(assistant_response.get("assistant_response"))
    assistant_response_id = (
        assistant_response.get("assistant_response_id")
        or assistant_response.get("id")
        or response.get("assistant_response_id")
    )
    summary = {
        "assistant_response_id": assistant_response_id,
        "citation_verification_id": assistant_response.get("citation_verification_id")
        or response.get("citation_verification_id"),
        "llm_execution_id": assistant_response.get("llm_execution_id") or response.get("llm_execution_id"),
        "prompt_package_id": assistant_response.get("prompt_package_id") or response.get("prompt_package_id"),
        "context_package_id": assistant_response.get("context_package_id") or response.get("context_package_id"),
        "assistant_id": assistant_response.get("assistant_id") or response.get("assistant_id"),
        "assistant_session_id": assistant_response.get("assistant_session_id") or response.get("assistant_session_id"),
        "response_status": assistant_response.get("response_status") or response.get("response_status"),
        "response_format": assistant_response.get("response_format") or response.get("response_format"),
        "response_language": assistant_response.get("response_language") or response.get("response_language"),
        "citation_verification_passed": bool(
            assistant_response.get("citation_verification_passed")
            if "citation_verification_passed" in assistant_response
            else response.get("citation_verification_passed")
        ),
        "verified_citation_count": assistant_response.get("verified_citation_count")
        or response.get("verified_citation_count"),
        "missing_citation_count": assistant_response.get("missing_citation_count")
        if "missing_citation_count" in assistant_response
        else response.get("missing_citation_count"),
        "invalid_citation_count": assistant_response.get("invalid_citation_count")
        if "invalid_citation_count" in assistant_response
        else response.get("invalid_citation_count"),
        "final_response_created": True,
        "citation_verification_completed": True,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }
    return [
        _record(
            runtime_domain="assistant_response",
            record_type="assistant_response",
            record_key=str(
                assistant_response_id or _stable_key(summary.get("citation_verification_id"), "assistant-response")
            ),
            artifact_id=artifact_id,
            provider="assistant_response",
            execution_status=str(summary.get("response_status") or "completed"),
            payload=assistant_response,
            summary=summary,
            validation={
                "blocking_issues": assistant_response.get("blocking_issues") or [],
                "warnings": assistant_response.get("warnings") or [],
            },
            metrics={
                "verified_citation_count": summary.get("verified_citation_count"),
                "missing_citation_count": summary.get("missing_citation_count"),
                "invalid_citation_count": summary.get("invalid_citation_count"),
            },
        )
    ]


def _conversation_runtime_records(
    conversation_runtime: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    conversation = _as_dict(conversation_runtime.get("conversation"))
    turn = _as_dict(conversation_runtime.get("conversation_turn"))
    conversation_id = (
        conversation_runtime.get("conversation_id")
        or conversation.get("conversation_id")
        or turn.get("conversation_id")
    )
    turn_id = conversation_runtime.get("conversation_turn_id") or turn.get("conversation_turn_id")
    record_type = "conversation_turn" if turn_id else "conversation"
    record_key = str(
        turn_id
        or conversation_id
        or _stable_key(conversation_runtime.get("assistant_response_id"), "conversation-runtime")
    )
    summary = {
        "conversation_id": conversation_id,
        "conversation_turn_id": turn_id,
        "assistant_id": conversation_runtime.get("assistant_id")
        or conversation.get("assistant_id")
        or turn.get("assistant_id"),
        "assistant_session_id": conversation_runtime.get("assistant_session_id")
        or conversation.get("assistant_session_id")
        or turn.get("assistant_session_id"),
        "assistant_run_id": conversation_runtime.get("assistant_run_id") or turn.get("assistant_run_id"),
        "assistant_runtime_trace_available": bool(
            conversation_runtime.get("assistant_runtime_trace_available")
            or turn.get("assistant_runtime_trace_available")
        ),
        "assistant_response_id": conversation_runtime.get("assistant_response_id") or turn.get("assistant_response_id"),
        "conversation_status": conversation_runtime.get("conversation_status")
        or conversation.get("conversation_status"),
        "turn_index": conversation_runtime.get("turn_index")
        if "turn_index" in conversation_runtime
        else turn.get("turn_index"),
        "turn_role": conversation_runtime.get("turn_role") or turn.get("turn_role"),
        "turn_status": conversation_runtime.get("turn_status") or turn.get("turn_status"),
        "conversation_created": bool(
            conversation_runtime.get("conversation_created") or conversation.get("conversation_created")
        ),
        "conversation_turn_created": bool(
            conversation_runtime.get("conversation_turn_created") or turn.get("conversation_turn_created")
        ),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }
    return [
        _record(
            runtime_domain="conversation_runtime",
            record_type=record_type,
            record_key=record_key,
            artifact_id=artifact_id,
            provider="conversation_runtime",
            execution_status=str(summary.get("turn_status") or summary.get("conversation_status") or "active"),
            payload=conversation_runtime,
            summary=summary,
            validation={
                "blocking_issues": conversation_runtime.get("blocking_issues") or [],
                "warnings": conversation_runtime.get("warnings") or [],
            },
            metrics={"turn_index": summary.get("turn_index")},
        )
    ]


def _chat_runtime_records(
    chat_runtime: dict[str, Any], *, artifact_id: str | None
) -> list[RuntimePersistenceRecordDescriptor]:
    summary = {
        "conversation_id": chat_runtime.get("conversation_id"),
        "assistant_session_id": chat_runtime.get("assistant_session_id"),
        "assistant_run_id": chat_runtime.get("assistant_run_id"),
        "retrieval_plan_id": chat_runtime.get("retrieval_plan_id"),
        "execution_plan_id": chat_runtime.get("execution_plan_id"),
        "search_execution_id": chat_runtime.get("search_execution_id"),
        "context_package_id": chat_runtime.get("context_package_id"),
        "prompt_package_id": chat_runtime.get("prompt_package_id"),
        "gateway_id": chat_runtime.get("gateway_id"),
        "llm_execution_id": chat_runtime.get("llm_execution_id"),
        "citation_verification_id": chat_runtime.get("citation_verification_id"),
        "assistant_response_id": chat_runtime.get("assistant_response_id"),
        "chat_completed": bool(chat_runtime.get("chat_completed")),
        "conversation_turns_created": chat_runtime.get("conversation_turns_created"),
        "assistant_runtime_trace_available": bool(chat_runtime.get("assistant_runtime_trace_available")),
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }
    record_key = str(
        chat_runtime.get("assistant_response_id")
        or chat_runtime.get("conversation_id")
        or _stable_key(chat_runtime.get("assistant_run_id"), "chat-runtime")
    )
    return [
        _record(
            runtime_domain="chat_runtime",
            record_type="chat_response",
            record_key=record_key,
            artifact_id=artifact_id,
            provider="chat_runtime",
            execution_status="completed" if summary["chat_completed"] else "blocked",
            payload=chat_runtime,
            summary=summary,
            validation={
                "blocking_issues": chat_runtime.get("blocking_issues") or [],
                "warnings": chat_runtime.get("warnings") or [],
            },
            metrics={"conversation_turns_created": summary.get("conversation_turns_created")},
        )
    ]


def build_runtime_persistence_records(
    *,
    execution_id: str,
    artifact_id: str | None,
    runtime_outputs: dict[str, Any],
) -> list[RuntimePersistenceRecordDescriptor]:
    records: list[RuntimePersistenceRecordDescriptor] = []
    if runtime_outputs.get("storage") is not None:
        records.extend(_storage_records(runtime_outputs["storage"], execution_id=execution_id, artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("processing"), dict):
        records.extend(_processing_records(runtime_outputs["processing"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("chunk"), dict):
        records.extend(_chunk_records(runtime_outputs["chunk"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("knowledge_publication"), dict):
        records.extend(_publication_records(runtime_outputs["knowledge_publication"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("knowledge_index"), dict):
        records.extend(_knowledge_index_records(runtime_outputs["knowledge_index"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("knowledge_lifecycle"), dict):
        records.extend(_knowledge_lifecycle_records(runtime_outputs["knowledge_lifecycle"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("knowledge_fts"), dict):
        records.extend(_knowledge_fts_records(runtime_outputs["knowledge_fts"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("embedding_runtime"), dict):
        records.extend(_embedding_runtime_records(runtime_outputs["embedding_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("vector_index_runtime"), dict):
        records.extend(_vector_index_runtime_records(runtime_outputs["vector_index_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("semantic_search_runtime"), dict):
        records.extend(
            _semantic_search_runtime_records(runtime_outputs["semantic_search_runtime"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("hybrid_search_runtime"), dict):
        records.extend(
            _hybrid_search_runtime_records(runtime_outputs["hybrid_search_runtime"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("workflow_runtime"), dict):
        records.extend(_workflow_runtime_records(runtime_outputs["workflow_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("assistant_runtime"), dict):
        records.extend(_assistant_runtime_records(runtime_outputs["assistant_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("assistant_retrieval_runtime"), dict):
        records.extend(
            _assistant_retrieval_runtime_records(
                runtime_outputs["assistant_retrieval_runtime"], artifact_id=artifact_id
            )
        )
    if isinstance(runtime_outputs.get("assistant_retrieval_execution_readiness"), dict):
        records.extend(
            _assistant_retrieval_execution_readiness_records(
                runtime_outputs["assistant_retrieval_execution_readiness"], artifact_id=artifact_id
            )
        )
    if isinstance(runtime_outputs.get("assistant_search_execution"), dict):
        records.extend(
            _assistant_search_execution_records(runtime_outputs["assistant_search_execution"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("assistant_context_builder"), dict):
        records.extend(
            _assistant_context_builder_records(runtime_outputs["assistant_context_builder"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("assistant_prompt_assembly"), dict):
        records.extend(
            _assistant_prompt_assembly_records(runtime_outputs["assistant_prompt_assembly"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("assistant_llm_gateway"), dict):
        records.extend(
            _assistant_llm_gateway_records(runtime_outputs["assistant_llm_gateway"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("assistant_llm_execution"), dict):
        records.extend(
            _assistant_llm_execution_records(runtime_outputs["assistant_llm_execution"], artifact_id=artifact_id)
        )
    if isinstance(runtime_outputs.get("assistant_citation_verification"), dict):
        records.extend(
            _assistant_citation_verification_records(
                runtime_outputs["assistant_citation_verification"], artifact_id=artifact_id
            )
        )
    if isinstance(runtime_outputs.get("assistant_response"), dict):
        records.extend(_assistant_response_records(runtime_outputs["assistant_response"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("conversation_runtime"), dict):
        records.extend(_conversation_runtime_records(runtime_outputs["conversation_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("chat_runtime"), dict):
        records.extend(_chat_runtime_records(runtime_outputs["chat_runtime"], artifact_id=artifact_id))
    if isinstance(runtime_outputs.get("enterprise_search"), dict):
        records.extend(_search_records(runtime_outputs["enterprise_search"], artifact_id=artifact_id))
    return records


def build_runtime_persistence_gateway(
    *,
    execution_id: str | None,
    artifact_id: str | None,
    runtime_outputs: dict[str, Any],
) -> dict[str, Any]:
    session = serialize_runtime_persistence_session(
        build_runtime_persistence_session(
            execution_id=execution_id, artifact_id=artifact_id, runtime_outputs=runtime_outputs
        )
    )
    ready = bool(session.get("persistence_session_ready"))
    records = (
        build_runtime_persistence_records(
            execution_id=str(execution_id),
            artifact_id=artifact_id,
            runtime_outputs=runtime_outputs,
        )
        if ready and execution_id
        else []
    )
    serialized_records = [
        {
            "runtime_domain": record.runtime_domain,
            "record_type": record.record_type,
            "record_key": record.record_key,
            "artifact_id": record.artifact_id,
            "processing_session_id": record.processing_session_id,
            "provider": record.provider,
            "execution_status": record.execution_status,
            "content_hash": record.content_hash,
            "summary": record.summary,
            "validation": record.validation,
            "metrics": record.metrics,
        }
        for record in records
    ]
    return {
        "runtime_persistence_gateway_schema_version": RUNTIME_PERSISTENCE_GATEWAY_SCHEMA_VERSION,
        "persistence_gateway_ready": ready,
        "gateway_status": RUNTIME_PERSISTENCE_GATEWAY_STATUS_READY
        if ready
        else RUNTIME_PERSISTENCE_GATEWAY_STATUS_BLOCKED,
        "persistence_session": session,
        "record_count": len(records),
        "records": serialized_records,
        "blocking_issues": session.get("blocking_issues") or [],
        "warnings": session.get("warnings") or [],
        "next_available_actions": [
            {
                "action": "persist_runtime_outputs",
                "available": ready,
                "status": "ready" if ready else "blocked",
                "reason": None if ready else "persistence_gateway_blocked",
            }
        ],
        "persistence_status": "not_persisted",
    }
