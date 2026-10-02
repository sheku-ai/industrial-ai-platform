"""Executable PostgreSQL FTS runtime over persistent knowledge chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.knowledge_fts import KnowledgeIndexRepository
from app.services.knowledge_fts_gateway import build_knowledge_fts_gateway
from app.services.knowledge_fts_session import KNOWLEDGE_FTS_RUNTIME_VERSION, normalize_fts_query, sort_issues

KNOWLEDGE_FTS_RUNTIME_SCHEMA_VERSION = "1"
FTS_SEARCH_STATUS_BLOCKED = "blocked"
FTS_SEARCH_STATUS_COMPLETED = "completed"
FTS_SEARCH_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class KnowledgeFtsRuntimeResult:
    fts_session_id: str | None
    fts_search_status: str
    query: str
    normalized_query: str
    organization_id: str | None = None
    total_count: int = 0
    offset: int = 0
    limit: int = 5
    has_more: bool = False
    facets: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    fts_validation: dict[str, Any] = field(default_factory=dict)
    fts_projection: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _stable_digest(*parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _fallback_snippet(text: str, query: str, *, max_chars: int = 220) -> str:
    if len(text) <= max_chars:
        return text
    normalized = normalize_fts_query(query).lower()
    tokens = [token for token in re.findall(r"[a-z0-9]+", normalized) if token]
    lowered = text.lower()
    positions = [lowered.find(token) for token in tokens if lowered.find(token) >= 0]
    start = max(0, min(positions) - 48) if positions else 0
    end = min(len(text), start + max_chars)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet


def _citation(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    citation_digest = _stable_digest(
        record.get("publication_id"),
        record.get("knowledge_chunk_id"),
        record.get("chunk_index"),
        record.get("content_hash"),
    )
    citation_id = f"citation:{citation_digest}"
    return {
        "citation_id": citation_id,
        "source": "knowledge_chunk",
        "organization_id": record.get("organization_id"),
        "artifact_id": record.get("artifact_id"),
        "publication_id": record.get("publication_id"),
        "knowledge_document_id": record.get("knowledge_document_id"),
        "knowledge_chunk_id": record.get("knowledge_chunk_id"),
        "published_chunk_id": record.get("published_chunk_id"),
        "chunk_index": record.get("chunk_index"),
        "content_hash": record.get("content_hash"),
        "document_record_id": metadata.get("document_record_id"),
        "document_title": metadata.get("document_title"),
        "original_filename": metadata.get("original_filename"),
        "document_type_name": metadata.get("document_type_name"),
        "collection_name": metadata.get("collection_name"),
        "document_href": (
            f"/documents#document-{metadata.get('document_record_id')}"
            if metadata.get("document_record_id")
            else None
        ),
    }


def _serialize_result(record: dict[str, Any], *, rank: int, query: str) -> dict[str, Any]:
    text = str(record.get("text") or "")
    snippet = record.get("snippet") or _fallback_snippet(text, query)
    highlighted_snippet = record.get("highlighted_snippet") or snippet
    citation = _citation(record)
    score = float(record.get("score") or 0.0)
    return {
        "search_result_id": f"search-result:{_stable_digest(citation.get('citation_id'), rank, score)}",
        "rank": rank,
        "ranking_position": rank,
        "score": round(score, 8),
        "ranking_model": "postgres_ts_rank_cd_simple_v1",
        "organization_id": record.get("organization_id"),
        "artifact_id": record.get("artifact_id"),
        "publication_id": record.get("publication_id"),
        "knowledge_document_id": record.get("knowledge_document_id"),
        "knowledge_chunk_id": record.get("knowledge_chunk_id"),
        "published_chunk_id": record.get("published_chunk_id"),
        "chunk_index": record.get("chunk_index"),
        "text": text,
        "text_preview": text[:320],
        "snippet": snippet,
        "highlighted_snippet": highlighted_snippet,
        "content_hash": record.get("content_hash"),
        "semantic_hash": record.get("semantic_hash"),
        "content_type": record.get("content_type"),
        "chunk_scope": record.get("chunk_scope"),
        "citation": citation,
        "metadata": dict(record.get("metadata") or {}),
        "ranking_trace": {
            "ranking_model": "postgres_ts_rank_cd_simple_v1",
            "postgres_rank_function": "ts_rank_cd",
            "fts_config": "simple",
            "score": round(score, 8),
            "tie_breakers": ["score_desc", "knowledge_document_id", "chunk_index", "knowledge_chunk_id"],
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
            "semantic_search_used": False,
            "embeddings_required": False,
            "ai_required": False,
        },
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": True,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def validate_fts_results(results: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for position, result in enumerate(results):
        if not result.get("search_result_id"):
            blocking_issues.append(
                {
                    "code": "search_result_id_missing",
                    "severity": "blocking",
                    "component": "knowledge_fts_result",
                    "item_id": str(position),
                    "message": "Each FTS result requires search_result_id.",
                }
            )
        if not result.get("knowledge_chunk_id"):
            blocking_issues.append(
                {
                    "code": "knowledge_chunk_id_missing",
                    "severity": "blocking",
                    "component": "knowledge_fts_result",
                    "item_id": str(position),
                    "message": "Each FTS result requires knowledge_chunk_id.",
                }
            )
        if not result.get("highlighted_snippet"):
            blocking_issues.append(
                {
                    "code": "highlighted_snippet_missing",
                    "severity": "blocking",
                    "component": "knowledge_fts_result",
                    "item_id": str(position),
                    "message": "Each FTS result requires highlighted_snippet.",
                }
            )
        citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
        if citation.get("source") != "knowledge_chunk":
            blocking_issues.append(
                {
                    "code": "citation_source_invalid",
                    "severity": "blocking",
                    "component": "knowledge_fts_citation",
                    "item_id": str(position),
                    "message": "FTS citations must use source=knowledge_chunk.",
                }
            )
    for position, citation in enumerate(citations):
        if not citation.get("citation_id"):
            blocking_issues.append(
                {
                    "code": "citation_id_missing",
                    "severity": "blocking",
                    "component": "knowledge_fts_citation",
                    "item_id": str(position),
                    "message": "Each FTS citation requires citation_id.",
                }
            )
    return {
        "fts_validation_schema_version": "1",
        "validation_status": FTS_SEARCH_STATUS_BLOCKED if blocking_issues else "valid",
        "valid": not blocking_issues,
        "result_count": len(results),
        "citation_count": len(citations),
        "matches_found": bool(results),
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": True,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
    }


def serialize_knowledge_fts_result(result: KnowledgeFtsRuntimeResult) -> dict[str, Any]:
    completed = result.fts_search_status == FTS_SEARCH_STATUS_COMPLETED
    return {
        "knowledge_fts_runtime_schema_version": KNOWLEDGE_FTS_RUNTIME_SCHEMA_VERSION,
        "knowledge_fts_runtime_version": KNOWLEDGE_FTS_RUNTIME_VERSION,
        "fts_session_id": result.fts_session_id,
        "fts_search_status": result.fts_search_status,
        "fts_search_completed": completed,
        "fts_search_succeeded": completed,
        "fts_search_used": completed,
        "query": result.query,
        "normalized_query": result.normalized_query,
        "organization_id": result.organization_id,
        "result_count": len(result.results),
        "matches_found": bool(result.results),
        "total_count": result.total_count,
        "offset": result.offset,
        "limit": result.limit,
        "has_more": result.has_more,
        "facets": dict(result.facets),
        "ranking_model": "postgres_ts_rank_cd_simple_v1",
        "results": list(result.results),
        "citations": list(result.citations),
        "fts_validation": dict(result.fts_validation),
        "fts_projection": dict(result.fts_projection),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": completed,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "persistence_status": "not_persisted",
    }


def build_knowledge_fts_health(db: Session) -> dict[str, Any]:
    repository = KnowledgeIndexRepository(db)
    health = repository.fts_health()
    return {
        "knowledge_fts_health_schema_version": "1",
        "fts_healthy": bool(health.get("fts_projection_ready")) and bool(health.get("fts_index_valid")),
        **health,
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
    }


def build_knowledge_fts_search(
    db: Session,
    *,
    query: str,
    top_k: int | None = None,
    offset: int = 0,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    include_facets: bool = False,
    include_debug: bool = False,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    repository = KnowledgeIndexRepository(db)
    projection = repository.fts_health()
    search_filters = dict(filters or {})
    organization_id = search_filters.get("organization_id")
    gateway = build_knowledge_fts_gateway(
        query=query,
        top_k=top_k,
        offset=offset,
        limit=limit,
        filters=search_filters,
        indexed_chunk_count=repository.indexed_chunk_count(organization_id=organization_id),
    )
    fts_session = gateway.get("fts_session") if isinstance(gateway.get("fts_session"), dict) else {}
    warnings = list(gateway.get("warnings") or [])
    if gateway.get("blocking_issues"):
        result = KnowledgeFtsRuntimeResult(
            fts_session_id=fts_session.get("fts_session_id"),
            fts_search_status=FTS_SEARCH_STATUS_BLOCKED,
            query=query,
            normalized_query=fts_session.get("normalized_query") or normalize_fts_query(query),
            organization_id=str(organization_id) if organization_id else None,
            offset=int(fts_session.get("offset") or 0),
            limit=int(fts_session.get("limit") or limit or top_k or 5),
            fts_projection=projection,
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=warnings,
            next_available_actions=[
                {
                    "action": "execute_postgres_fts_search",
                    "available": False,
                    "status": "blocked",
                    "reason": "knowledge_fts_gateway_blocked",
                }
            ],
        )
        return {**serialize_knowledge_fts_result(result), "knowledge_fts_gateway": gateway}

    search_filters = fts_session.get("filters") if isinstance(fts_session.get("filters"), dict) else {}
    organization_id = search_filters.get("organization_id")
    search_page = repository.search_fts(
        query=fts_session.get("normalized_query") or query,
        top_k=int(fts_session.get("top_k") or 5),
        offset=int(fts_session.get("offset") or 0),
        limit=int(fts_session.get("limit") or limit or fts_session.get("top_k") or 5),
        artifact_id=search_filters.get("artifact_id"),
        publication_id=search_filters.get("publication_id"),
        knowledge_document_id=search_filters.get("knowledge_document_id"),
        content_type=search_filters.get("content_type"),
        chunk_scope=search_filters.get("chunk_scope"),
        status=search_filters.get("status") or "indexed",
        organization_id=organization_id,
        include_facets=include_facets,
    )
    records = search_page.get("records") if isinstance(search_page.get("records"), list) else []
    results = [_serialize_result(record, rank=index + 1, query=query) for index, record in enumerate(records)]
    citations = [dict(result["citation"]) for result in results]
    validation = validate_fts_results(results, citations)
    warnings.extend(validation.get("warnings") or [])
    status = FTS_SEARCH_STATUS_COMPLETED if validation.get("valid") else FTS_SEARCH_STATUS_FAILED
    result = KnowledgeFtsRuntimeResult(
        fts_session_id=fts_session.get("fts_session_id"),
        fts_search_status=status,
        query=query,
        normalized_query=fts_session.get("normalized_query") or normalize_fts_query(query),
        organization_id=str(organization_id) if organization_id else None,
        total_count=int(search_page.get("total_count") or 0),
        offset=int(search_page.get("offset") or 0),
        limit=int(search_page.get("limit") or 0),
        has_more=bool(search_page.get("has_more")),
        facets=dict(search_page.get("facets") or {}),
        results=results,
        citations=citations,
        fts_validation=validation,
        fts_projection=projection,
        blocking_issues=validation.get("blocking_issues") or [],
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "derive_vector_index",
                "available": False,
                "status": "blocked",
                "reason": "vector_indexes_not_in_fts_runtime_scope",
            }
        ],
    )
    payload = {**serialize_knowledge_fts_result(result), "knowledge_fts_gateway": gateway}
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        execution_digest = _stable_digest(
            payload.get("fts_session_id"),
            payload.get("normalized_query"),
            payload.get("result_count"),
        )
        execution_id = f"knowledge-fts:{execution_digest}"
        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=execution_id,
            artifact_id=results[0].get("artifact_id") if results else None,
            runtime_outputs={"knowledge_fts": payload},
        )
    return payload
