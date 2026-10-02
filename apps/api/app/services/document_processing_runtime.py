"""Processing runtime foundation for verified storage handoff.

This module is the executable Processing domain slice.
It stays provider-neutral at the Processing boundary and reads verified content
through the storage provider runtime.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.services.storage_provider_registry import get_storage_provider_registry
from app.services.storage_provider_runtime import get_storage_provider_runtime_adapter

PROCESSING_RUNTIME_SCHEMA_VERSION = "1"
PROCESSING_RESULT_SCHEMA_VERSION = "1"
TEXT_PARSER_SCHEMA_VERSION = "1"

PROCESSING_STATUS_BLOCKED = "blocked"
PROCESSING_STATUS_COMPLETED = "completed"
PROCESSING_STATUS_FAILED = "failed"

SUPPORTED_TEXT_CONTENT_TYPES = {
    "text/plain",
}


@dataclass(frozen=True)
class TextParserResult:
    parser_name: str
    parser_version: str
    content_type: str | None
    text: str
    char_count: int
    line_count: int
    paragraph_count: int
    content_sha256: str
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ProcessingRuntimeResult:
    artifact_id: str | None
    processing_session_id: str | None
    handoff_session_id: str | None
    processing_status: str
    parser_runtime: dict[str, Any]
    processing_result: dict[str, Any]
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


class ProcessingRuntimeError(RuntimeError):
    """Raised when the processing runtime cannot safely execute."""


def _issue(
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


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items, key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id")))
    )


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes | bytearray):
        value = bytes(value).decode("utf-8", errors="replace")
    text = str(value).replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    normalized = "\n".join(lines)
    while "\n\n\n" in normalized:
        normalized = normalized.replace("\n\n\n", "\n\n")
    return normalized.strip()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_type_root(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _paragraph_count(text: str) -> int:
    if not text:
        return 0
    return len([part for part in text.split("\n\n") if part.strip()])


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _extract_source_summary(handoff_session: dict[str, Any]) -> dict[str, Any]:
    source_summary = handoff_session.get("source_storage_summary")
    if isinstance(source_summary, dict):
        return source_summary
    nested_handoff = handoff_session.get("handoff_session")
    if isinstance(nested_handoff, dict) and isinstance(nested_handoff.get("source_storage_summary"), dict):
        return nested_handoff["source_storage_summary"]
    return {}


def _extract_processing_session(handoff_session: dict[str, Any]) -> dict[str, Any]:
    processing_session = handoff_session.get("processing_session")
    if isinstance(processing_session, dict):
        return processing_session
    nested_handoff = handoff_session.get("handoff_session")
    if isinstance(nested_handoff, dict) and isinstance(nested_handoff.get("processing_session"), dict):
        return nested_handoff["processing_session"]
    return {}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _organization_id_from_processing_context(
    db: Session | None,
    *,
    handoff_session: dict[str, Any],
    search_config: dict[str, Any] | None,
) -> str | None:
    config = _dict_value(search_config)
    filters = _dict_value(config.get("filters"))
    source_summary = _extract_source_summary(handoff_session)
    processing_session = _extract_processing_session(handoff_session)
    for value in (
        filters.get("organization_id"),
        config.get("organization_id"),
        handoff_session.get("organization_id"),
        source_summary.get("organization_id"),
        processing_session.get("organization_id"),
    ):
        if value:
            return str(value)
    artifact_id = handoff_session.get("artifact_id") or source_summary.get("artifact_id")
    if db is not None and artifact_id:
        try:
            artifact = db.get(Artifact, uuid.UUID(str(artifact_id)))
        except (TypeError, ValueError):
            artifact = None
        if artifact is not None and artifact.organization_id:
            return str(artifact.organization_id)
    return None


def _scoped_search_config(search_config: dict[str, Any] | None, organization_id: str | None) -> dict[str, Any]:
    scoped = dict(search_config or {})
    if not organization_id:
        return scoped
    filters = dict(_dict_value(scoped.get("filters")))
    filters.setdefault("organization_id", organization_id)
    scoped["filters"] = filters
    scoped.setdefault("organization_id", organization_id)
    return scoped


def validate_processing_runtime_handoff(handoff_session: dict[str, Any]) -> dict[str, Any]:
    source_summary = _extract_source_summary(handoff_session)
    processing_session = _extract_processing_session(handoff_session)
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not handoff_session.get("processing_handoff_ready"):
        blocking_issues.append(
            _issue(
                "processing_handoff_not_ready",
                "Processing runtime requires processing_handoff_ready=true.",
                component="processing_handoff",
            )
        )
    if not handoff_session.get("artifact_id"):
        blocking_issues.append(
            _issue("artifact_id_missing", "Processing runtime requires an artifact_id.", component="processing_runtime")
        )
    if not processing_session.get("processing_session_id"):
        blocking_issues.append(
            _issue(
                "processing_session_missing",
                "Processing runtime requires a processing_session_id.",
                component="processing_session",
            )
        )
    if not source_summary.get("storage_verified"):
        blocking_issues.append(
            _issue("storage_not_verified", "Processing runtime requires verified storage.", component="storage")
        )
    if not source_summary.get("object_exists") or source_summary.get("deleted"):
        blocking_issues.append(
            _issue(
                "object_not_available", "Processing runtime requires an available stored object.", component="storage"
            )
        )
    if not source_summary.get("object_handle"):
        blocking_issues.append(
            _issue("object_handle_missing", "Processing runtime requires a storage object_handle.", component="storage")
        )

    content_type = _content_type_root(source_summary.get("content_type"))
    if content_type not in SUPPORTED_TEXT_CONTENT_TYPES:
        blocking_issues.append(
            _issue(
                "parser_not_supported",
                "Processing runtime foundation currently supports only text/plain parser execution.",
                component="parser_runtime",
                item_id=content_type or "unknown",
            )
        )

    if bool(source_summary.get("content_length") == 0):
        warnings.append(
            _issue(
                "empty_source_object",
                "Processing runtime received an empty source object.",
                component="parser_runtime",
                severity="warning",
            )
        )

    return {
        "validation_status": PROCESSING_STATUS_BLOCKED if blocking_issues else "ready",
        "blocking_issues": _sort_issues(blocking_issues),
        "warnings": _sort_issues(warnings),
    }


def _storage_provider_configuration(source_summary: dict[str, Any]) -> dict[str, Any]:
    object_handle = source_summary.get("object_handle")
    reference = (
        object_handle.get("reference")
        if isinstance(object_handle, dict) and isinstance(object_handle.get("reference"), dict)
        else {}
    )
    return {
        "provider_name": source_summary.get("storage_provider_name"),
        "provider_type": source_summary.get("storage_provider_type"),
        **({"storage_root": reference.get("storage_root")} if reference.get("storage_root") else {}),
    }


def _read_storage_object_content(
    source_summary: dict[str, Any], handoff_session: dict[str, Any]
) -> tuple[bytes | None, dict[str, Any]]:
    provider = get_storage_provider_registry().resolve(
        source_summary.get("storage_provider_name") or source_summary.get("storage_provider_type"),
        configuration=_storage_provider_configuration(source_summary),
    )
    object_handle = source_summary.get("object_handle")
    storage_descriptor = {
        "artifact_id": source_summary.get("artifact_id") or handoff_session.get("artifact_id"),
        "upload_session_id": source_summary.get("upload_session_id") or handoff_session.get("upload_session_id"),
        "object_handle": object_handle,
        "content_type": source_summary.get("content_type"),
        "requested_by": "processing-runtime",
    }
    runtime_operation = get_storage_provider_runtime_adapter().build_operation(
        storage_provider=provider,
        operation="get_object",
        storage_descriptor=storage_descriptor,
        execute=True,
    )
    runtime_dict = runtime_operation.as_dict()
    result = runtime_dict.get("result") if isinstance(runtime_dict.get("result"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    content = metadata.get("content")
    if isinstance(content, bytes):
        return content, runtime_dict
    if isinstance(content, bytearray):
        return bytes(content), runtime_dict
    if isinstance(content, str):
        return content.encode("utf-8"), runtime_dict
    return None, runtime_dict


def parse_text_plain(content: bytes, *, content_type: str | None) -> dict[str, Any]:
    text = _normalize_text(content)
    warnings: list[dict[str, Any]] = []
    if not text:
        warnings.append(
            _issue(
                "parsed_text_empty",
                "Text parser produced empty text.",
                component="text_parser",
                severity="warning",
            )
        )
    result = TextParserResult(
        parser_name="text/plain",
        parser_version="text_plain_parser/1.0",
        content_type=content_type,
        text=text,
        char_count=len(text),
        line_count=_line_count(text),
        paragraph_count=_paragraph_count(text),
        content_sha256=_sha256_text(text),
        warnings=warnings,
    )
    return {
        "text_parser_schema_version": TEXT_PARSER_SCHEMA_VERSION,
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "content_type": result.content_type,
        "text": result.text,
        "char_count": result.char_count,
        "line_count": result.line_count,
        "paragraph_count": result.paragraph_count,
        "content_sha256": result.content_sha256,
        "warnings": list(result.warnings),
    }


def build_processing_result(
    *,
    handoff_session: dict[str, Any],
    source_summary: dict[str, Any],
    parser_result: dict[str, Any],
    storage_read_trace: dict[str, Any],
) -> dict[str, Any]:
    text = parser_result.get("text") or ""
    return {
        "processing_result_schema_version": PROCESSING_RESULT_SCHEMA_VERSION,
        "artifact_id": handoff_session.get("artifact_id"),
        "document_record_id": source_summary.get("document_record_id") or handoff_session.get("document_record_id"),
        "document_version_id": source_summary.get("document_version_id") or handoff_session.get("document_version_id"),
        "upload_session_id": handoff_session.get("upload_session_id"),
        "execution_session_id": handoff_session.get("execution_session_id"),
        "processing_session_id": (_extract_processing_session(handoff_session) or {}).get("processing_session_id"),
        "processing_completed": True,
        "processing_succeeded": True,
        "processing_failed": False,
        "parser_executed": True,
        "parser_name": parser_result.get("parser_name"),
        "parser_version": parser_result.get("parser_version"),
        "text_extracted": bool(text),
        "text_char_count": parser_result.get("char_count"),
        "line_count": parser_result.get("line_count"),
        "paragraph_count": parser_result.get("paragraph_count"),
        "content_sha256": parser_result.get("content_sha256"),
        "source_content_type": source_summary.get("content_type"),
        "source_checksum": source_summary.get("checksum"),
        "source_content_length": source_summary.get("content_length"),
        "chunks_created": False,
        "embeddings_created": False,
        "ai_required": False,
        "vector_store_required": False,
        "persistence_status": "not_persisted",
        "storage_read_trace": {
            "operation": storage_read_trace.get("operation"),
            "state": storage_read_trace.get("state"),
            "invoked": bool(storage_read_trace.get("invoked")),
            "execution_allowed": bool(storage_read_trace.get("execution_allowed")),
        },
        "parsed_text": text,
    }


def serialize_processing_runtime_result(result: ProcessingRuntimeResult) -> dict[str, Any]:
    return {
        "processing_runtime_schema_version": PROCESSING_RUNTIME_SCHEMA_VERSION,
        "artifact_id": result.artifact_id,
        "processing_session_id": result.processing_session_id,
        "handoff_session_id": result.handoff_session_id,
        "processing_status": result.processing_status,
        "processing_completed": result.processing_status == PROCESSING_STATUS_COMPLETED,
        "processing_succeeded": result.processing_status == PROCESSING_STATUS_COMPLETED,
        "processing_failed": result.processing_status == PROCESSING_STATUS_FAILED,
        "parser_runtime": dict(result.parser_runtime),
        "processing_result": dict(result.processing_result),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "chunks_created": False,
        "embeddings_created": False,
        "ai_required": False,
        "vector_store_required": False,
        "persistence_status": "not_persisted",
    }


def build_document_processing_execution(handoff_session: dict[str, Any]) -> dict[str, Any]:
    source_summary = _extract_source_summary(handoff_session)
    processing_session = _extract_processing_session(handoff_session)
    validation = validate_processing_runtime_handoff(handoff_session)
    warnings = list(validation["warnings"])

    if validation["blocking_issues"]:
        result = ProcessingRuntimeResult(
            artifact_id=handoff_session.get("artifact_id"),
            processing_session_id=processing_session.get("processing_session_id"),
            handoff_session_id=handoff_session.get("handoff_session_id"),
            processing_status=PROCESSING_STATUS_BLOCKED,
            parser_runtime={
                "parser_runtime_schema_version": "1",
                "parser_executed": False,
                "supported_content_types": sorted(SUPPORTED_TEXT_CONTENT_TYPES),
            },
            processing_result={
                "processing_result_schema_version": PROCESSING_RESULT_SCHEMA_VERSION,
                "processing_completed": False,
                "processing_succeeded": False,
                "processing_failed": False,
                "parser_executed": False,
            },
            blocking_issues=validation["blocking_issues"],
            warnings=warnings,
            next_available_actions=[
                {
                    "action": "start_processing",
                    "available": False,
                    "status": "blocked",
                    "reason": "processing_runtime_validation_blocked",
                }
            ],
        )
        return serialize_processing_runtime_result(result)

    content, storage_read_trace = _read_storage_object_content(source_summary, handoff_session)
    if content is None:
        blocking_issues = [
            _issue(
                "source_content_missing",
                "Processing runtime could not read source content from storage.",
                component="storage",
            )
        ]
        result = ProcessingRuntimeResult(
            artifact_id=handoff_session.get("artifact_id"),
            processing_session_id=processing_session.get("processing_session_id"),
            handoff_session_id=handoff_session.get("handoff_session_id"),
            processing_status=PROCESSING_STATUS_FAILED,
            parser_runtime={"parser_runtime_schema_version": "1", "parser_executed": False},
            processing_result={
                "processing_result_schema_version": PROCESSING_RESULT_SCHEMA_VERSION,
                "processing_completed": True,
                "processing_succeeded": False,
                "processing_failed": True,
                "parser_executed": False,
            },
            blocking_issues=blocking_issues,
            warnings=warnings,
            next_available_actions=[{"action": "retry_processing", "available": True, "status": "ready"}],
        )
        return serialize_processing_runtime_result(result)

    parser_result = parse_text_plain(content, content_type=source_summary.get("content_type"))
    warnings.extend(parser_result.get("warnings") or [])
    processing_result = build_processing_result(
        handoff_session=handoff_session,
        source_summary=source_summary,
        parser_result=parser_result,
        storage_read_trace=storage_read_trace,
    )
    runtime_result = ProcessingRuntimeResult(
        artifact_id=handoff_session.get("artifact_id"),
        processing_session_id=processing_session.get("processing_session_id"),
        handoff_session_id=handoff_session.get("handoff_session_id"),
        processing_status=PROCESSING_STATUS_COMPLETED,
        parser_runtime={
            "parser_runtime_schema_version": "1",
            "parser_executed": True,
            "parser_name": parser_result.get("parser_name"),
            "parser_version": parser_result.get("parser_version"),
            "supported_content_types": sorted(SUPPORTED_TEXT_CONTENT_TYPES),
            "result": {key: value for key, value in parser_result.items() if key != "text"},
        },
        processing_result=processing_result,
        blocking_issues=[],
        warnings=_sort_issues(warnings),
        next_available_actions=[
            {
                "action": "generate_chunks",
                "available": True,
                "status": "ready",
                "reason": "processing_result_available",
                "chunks_created": False,
            },
            {
                "action": "publish_to_knowledge",
                "available": False,
                "status": "blocked",
                "reason": "chunks_not_created",
            },
        ],
    )
    return serialize_processing_runtime_result(runtime_result)


def build_document_processing_and_chunk_execution(
    handoff_session: dict[str, Any],
    *,
    chunker_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Processing, then Chunk Runtime when parsed text is available."""

    from app.services.document_chunk_runtime import build_document_chunk_generation

    processing_execution = build_document_processing_execution(handoff_session)
    processing_result = processing_execution.get("processing_result")
    if not isinstance(processing_result, dict):
        processing_result = {}
    chunk_generation = build_document_chunk_generation(processing_result, chunker_config=chunker_config)
    return {
        "processing_chunk_execution_schema_version": "1",
        "artifact_id": processing_execution.get("artifact_id"),
        "document_record_id": processing_result.get("document_record_id"),
        "document_version_id": processing_result.get("document_version_id"),
        "processing_session_id": processing_execution.get("processing_session_id"),
        "processing_completed": bool(processing_execution.get("processing_completed")),
        "processing_succeeded": bool(processing_execution.get("processing_succeeded")),
        "parser_executed": bool((processing_execution.get("parser_runtime") or {}).get("parser_executed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "chunks_created": bool(chunk_generation.get("chunks_created")),
        "chunk_count": chunk_generation.get("chunk_count"),
        "processing_execution": processing_execution,
        "processing_result": processing_result,
        "chunk_generation": chunk_generation,
        "embeddings_created": False,
        "knowledge_published": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def _chunk_result_completed(chunk_result: dict[str, Any]) -> bool:
    return bool(
        chunk_result.get("chunk_status") == "completed"
        and chunk_result.get("chunk_generation_completed") is True
        and int(chunk_result.get("chunk_count") or 0) > 0
        and bool(chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else [])
    )


def build_document_processing_chunk_and_publication_execution(
    handoff_session: dict[str, Any],
    *,
    chunker_config: dict[str, Any] | None = None,
    publication_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Processing, Chunk Runtime, then Knowledge Publication Runtime."""

    from app.services.knowledge_publication_runtime import build_knowledge_publication

    chunk_execution = build_document_processing_and_chunk_execution(handoff_session, chunker_config=chunker_config)
    chunk_generation = chunk_execution.get("chunk_generation")
    if not isinstance(chunk_generation, dict):
        chunk_generation = {}
    chunk_result = (
        chunk_generation.get("chunk_result")
        if isinstance(chunk_generation.get("chunk_result"), dict)
        else chunk_generation
    )
    publication = build_knowledge_publication(chunk_result, publication_config=publication_config)
    return {
        "processing_chunk_publication_execution_schema_version": "1",
        "artifact_id": chunk_execution.get("artifact_id"),
        "document_record_id": chunk_execution.get("document_record_id"),
        "document_version_id": chunk_execution.get("document_version_id"),
        "processing_session_id": chunk_execution.get("processing_session_id"),
        "processing_completed": bool(chunk_execution.get("processing_completed")),
        "parser_executed": bool(chunk_execution.get("parser_executed")),
        "chunk_generation_completed": bool(chunk_result.get("chunk_generation_completed")),
        "chunks_created": _chunk_result_completed(chunk_result),
        "chunk_count": chunk_result.get("chunk_count"),
        "publication_completed": bool(publication.get("publication_completed")),
        "publication_succeeded": bool(publication.get("publication_succeeded")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "published_chunk_count": publication.get("published_chunk_count"),
        "processing_chunk_execution": chunk_execution,
        "processing_execution": chunk_execution.get("processing_execution"),
        "processing_result": chunk_execution.get("processing_result"),
        "chunk_generation": chunk_generation,
        "chunk_result": chunk_result,
        "knowledge_publication": publication,
        "publication_result": publication.get("publication_result")
        if isinstance(publication.get("publication_result"), dict)
        else publication,
        "embeddings_created": False,
        "semantic_index_created": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def build_document_processing_publication_and_search_execution(
    handoff_session: dict[str, Any],
    *,
    db: Session | None = None,
    query: str,
    top_k: int | None = None,
    chunker_config: dict[str, Any] | None = None,
    publication_config: dict[str, Any] | None = None,
    search_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Processing, Chunk Runtime, Publication Runtime, then Enterprise Search."""

    from app.services.enterprise_search_runtime import build_enterprise_search
    from app.services.knowledge_index_runtime import build_knowledge_index

    publication_execution = build_document_processing_chunk_and_publication_execution(
        handoff_session,
        chunker_config=chunker_config,
        publication_config=publication_config,
    )
    publication_result = publication_execution.get("publication_result")
    if not isinstance(publication_result, dict):
        publication_result = {}
    knowledge_index = (
        build_knowledge_index(db, publication_result)
        if db is not None
        else {
            "index_status": "blocked",
            "index_completed": False,
            "index_succeeded": False,
            "blocking_issues": [
                {
                    "code": "database_session_missing",
                    "severity": "blocking",
                    "component": "knowledge_index",
                    "item_id": None,
                    "message": "Knowledge indexing requires a database session.",
                }
            ],
        }
    )
    organization_id = _organization_id_from_processing_context(
        db,
        handoff_session=handoff_session,
        search_config=search_config,
    )
    search = build_enterprise_search(
        db=db,
        query=query,
        top_k=top_k,
        search_config=_scoped_search_config(search_config, organization_id),
    )
    return {
        "processing_publication_search_execution_schema_version": "1",
        "artifact_id": publication_execution.get("artifact_id"),
        "processing_session_id": publication_execution.get("processing_session_id"),
        "processing_completed": bool(publication_execution.get("processing_completed")),
        "parser_executed": bool(publication_execution.get("parser_executed")),
        "chunk_generation_completed": bool(
            (publication_execution.get("chunk_result") or {}).get("chunk_generation_completed")
        ),
        "chunks_created": _chunk_result_completed(publication_execution.get("chunk_result") or {}),
        "publication_completed": bool(publication_execution.get("publication_completed")),
        "publication_succeeded": bool(publication_execution.get("publication_succeeded")),
        "knowledge_published": bool(publication_execution.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "index_succeeded": bool(knowledge_index.get("index_succeeded")),
        "search_completed": bool(search.get("search_completed")),
        "search_succeeded": bool(search.get("search_succeeded")),
        "result_count": search.get("result_count"),
        "processing_publication_execution": publication_execution,
        "processing_execution": publication_execution.get("processing_execution"),
        "processing_result": publication_execution.get("processing_result"),
        "chunk_generation": publication_execution.get("chunk_generation"),
        "chunk_result": publication_execution.get("chunk_result"),
        "knowledge_publication": publication_execution.get("knowledge_publication"),
        "publication_result": publication_execution.get("publication_result"),
        "knowledge_index": knowledge_index,
        "enterprise_search": search,
        "search_result": search,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }
