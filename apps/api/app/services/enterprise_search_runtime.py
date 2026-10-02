"""Executable Enterprise Search runtime backed by PostgreSQL FTS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.core import Organization
from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.enterprise_search_gateway import build_enterprise_search_gateway
from app.services.enterprise_search_persistence import persist_enterprise_search_result
from app.services.enterprise_search_session import (
    ENTERPRISE_SEARCH_STATE_BLOCKED,
    issue,
    normalize_query_text,
    sort_issues,
)
from app.services.knowledge_index_search_gate import (
    evaluate_knowledge_index_search_gate_v1,
    serialize_knowledge_index_search_gate_v1,
)

ENTERPRISE_SEARCH_RUNTIME_SCHEMA_VERSION = "1"
SEARCH_STATUS_BLOCKED = "blocked"
SEARCH_STATUS_COMPLETED = "completed"
SEARCH_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class EnterpriseSearchRuntimeResult:
    search_session_id: str | None
    search_status: str
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
    search_validation: dict[str, Any] = field(default_factory=dict)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def validate_search_result(results: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for position, result in enumerate(results):
        if not result.get("search_result_id"):
            blocking_issues.append(
                issue(
                    "search_result_id_missing",
                    "Each search result requires search_result_id.",
                    component="search_result",
                    item_id=str(position),
                )
            )
        if not result.get("published_chunk_id"):
            blocking_issues.append(
                issue(
                    "published_chunk_id_missing",
                    "Each search result requires published_chunk_id.",
                    component="search_result",
                    item_id=str(position),
                )
            )
        citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
        if not citation:
            blocking_issues.append(
                issue(
                    "citation_missing",
                    "Each search result requires a citation.",
                    component="search_result",
                    item_id=str(position),
                )
            )
        if citation and citation.get("source") not in {"published_chunk", "knowledge_chunk"}:
            blocking_issues.append(
                issue(
                    "citation_source_invalid",
                    "Citation source must be published_chunk or knowledge_chunk.",
                    component="citation",
                    item_id=str(position),
                )
            )
        if (
            result.get("semantic_search_used") is not False
            or result.get("embeddings_required") is not False
            or result.get("ai_required") is not False
        ):
            blocking_issues.append(
                issue(
                    "semantic_ai_flags_enabled",
                    "Search result must keep semantic and AI flags disabled.",
                    component="search_result",
                    item_id=str(position),
                )
            )
    for position, citation in enumerate(citations):
        if not citation.get("citation_id"):
            blocking_issues.append(
                issue(
                    "citation_id_missing",
                    "Each citation requires citation_id.",
                    component="citation",
                    item_id=str(position),
                )
            )
    return {
        "search_validation_schema_version": "1",
        "validation_status": SEARCH_STATUS_BLOCKED if blocking_issues else "valid",
        "valid": not blocking_issues,
        "result_count": len(results),
        "citation_count": len(citations),
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": sort_issues(warnings),
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
    }


def serialize_enterprise_search_result(result: EnterpriseSearchRuntimeResult) -> dict[str, Any]:
    completed = result.search_status == SEARCH_STATUS_COMPLETED
    return {
        "enterprise_search_runtime_schema_version": ENTERPRISE_SEARCH_RUNTIME_SCHEMA_VERSION,
        "search_session_id": result.search_session_id,
        "search_status": result.search_status,
        "search_completed": completed,
        "search_succeeded": completed,
        "query": result.query,
        "normalized_query": result.normalized_query,
        "organization_id": result.organization_id,
        "ranking_model": "postgres_ts_rank_cd_simple_v1",
        "total_count": result.total_count,
        "result_count": len(result.results),
        "matches_found": bool(result.results),
        "offset": result.offset,
        "limit": result.limit,
        "has_more": result.has_more,
        "facets": dict(result.facets),
        "results": list(result.results),
        "citations": list(result.citations),
        "search_validation": dict(result.search_validation),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": completed,
        "persistence_status": "not_persisted",
    }


def _search_filters(search_config: dict[str, Any] | None) -> tuple[dict[str, Any], bool, bool]:
    filters: dict[str, Any] = {}
    include_facets = False
    include_debug = False
    if isinstance(search_config, dict):
        filters = dict(search_config.get("filters") or {})
        for key in (
            "organization_id",
            "artifact_id",
            "publication_id",
            "knowledge_document_id",
            "content_type",
            "chunk_scope",
            "status",
        ):
            if key in search_config and key not in filters:
                filters[key] = search_config[key]
        include_facets = bool(search_config.get("include_facets", False))
        include_debug = bool(search_config.get("include_debug", False))
    return filters, include_facets, include_debug


def _organization_scope_issues(db: Session | None, organization_id: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if not organization_id:
        return None, [
            issue(
                "organization_scope_required",
                "Enterprise search requires an explicit organization_id scope.",
                component="enterprise_search",
            )
        ]
    try:
        organization_uuid = uuid.UUID(str(organization_id))
    except (TypeError, ValueError):
        return None, [
            issue(
                "organization_scope_invalid",
                "Enterprise search organization_id must be a valid UUID.",
                component="enterprise_search",
            )
        ]
    if db is not None and db.get(Organization, organization_uuid) is None:
        return str(organization_uuid), [
            issue(
                "organization_scope_not_found",
                "Enterprise search organization_id does not exist.",
                component="enterprise_search",
                item_id=str(organization_uuid),
            )
        ]
    return str(organization_uuid), []


def _knowledge_index_gate_issues(
    db: Session | None,
    *,
    organization_id: str | None,
    search_filters: dict[str, Any],
    organization_issues: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if organization_issues or organization_id is None:
        return None, []
    if db is None:
        return None, [
            issue(
                "knowledge_index_evidence_database_required",
                "Enterprise Search requires PostgreSQL to verify Knowledge Index evidence.",
                component="knowledge_index_evidence",
            )
        ]

    gate = evaluate_knowledge_index_search_gate_v1(
        db,
        organization_id=uuid.UUID(organization_id),
        artifact_id=search_filters.get("artifact_id"),
        publication_id=search_filters.get("publication_id"),
        knowledge_document_id=search_filters.get("knowledge_document_id"),
    )
    payload = serialize_knowledge_index_search_gate_v1(gate)
    return payload, list(gate.blocking_issues)


def build_enterprise_search(
    *,
    db: Session | None = None,
    query: str,
    top_k: int | None = None,
    offset: int = 0,
    limit: int | None = None,
    include_facets: bool = False,
    include_debug: bool = False,
    search_config: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    repository = KnowledgeIndexRepository(db) if db is not None else None
    search_filters, config_include_facets, config_include_debug = _search_filters(search_config)
    include_facets = include_facets or config_include_facets
    include_debug = include_debug or config_include_debug
    organization_id, organization_issues = _organization_scope_issues(db, search_filters.get("organization_id"))
    if organization_id:
        search_filters["organization_id"] = organization_id

    knowledge_index_gate, knowledge_index_issues = _knowledge_index_gate_issues(
        db,
        organization_id=organization_id,
        search_filters=search_filters,
        organization_issues=organization_issues,
    )
    indexed_chunk_count = (
        repository.indexed_chunk_count(organization_id=organization_id)
        if repository is not None and organization_id
        else 0
    )
    gateway = build_enterprise_search_gateway(
        query=query,
        top_k=top_k,
        search_config={**dict(search_config or {}), "filters": search_filters},
        indexed_chunk_count=indexed_chunk_count,
    )
    search_session = gateway.get("search_session") if isinstance(gateway.get("search_session"), dict) else {}
    warnings = list(gateway.get("warnings") or [])
    blocking_issues = (
        list(organization_issues)
        + list(knowledge_index_issues)
        + list(gateway.get("blocking_issues") or [])
    )
    if blocking_issues:
        result = EnterpriseSearchRuntimeResult(
            search_session_id=search_session.get("search_session_id"),
            search_status=SEARCH_STATUS_BLOCKED,
            query=query,
            normalized_query=search_session.get("normalized_query") or normalize_query_text(query),
            organization_id=organization_id,
            offset=max(0, int(offset or 0)),
            limit=max(1, min(int(limit if limit is not None else top_k if top_k is not None else 5), 50)),
            results=[],
            citations=[],
            search_validation={
                "search_validation_schema_version": "1",
                "validation_status": ENTERPRISE_SEARCH_STATE_BLOCKED,
                "valid": False,
                "result_count": 0,
                "citation_count": 0,
                "blocking_issues": blocking_issues,
                "warnings": warnings,
                "semantic_search_used": False,
                "embeddings_required": False,
                "ai_required": False,
            },
            blocking_issues=blocking_issues,
            warnings=warnings,
            next_available_actions=[
                {
                    "action": "execute_enterprise_search",
                    "available": False,
                    "status": "blocked",
                    "reason": "search_gateway_validation_blocked",
                }
            ],
        )
        payload = {
            **serialize_enterprise_search_result(result),
            "search_gateway": gateway,
            "search_uses_postgresql": db is not None,
            "search_uses_postgresql_fts": False,
        }
        if knowledge_index_gate is not None:
            payload["knowledge_index_evidence_gate"] = knowledge_index_gate
        return payload

    from app.services.knowledge_fts_runtime import build_knowledge_fts_search

    fts_search = build_knowledge_fts_search(
        db,
        query=query,
        top_k=int(search_session.get("top_k") or 5),
        offset=offset,
        limit=limit,
        filters=search_filters,
        include_facets=include_facets,
        include_debug=include_debug,
        persist_snapshot=False,
    )
    results = fts_search.get("results") if isinstance(fts_search.get("results"), list) else []
    citations = fts_search.get("citations") if isinstance(fts_search.get("citations"), list) else []
    validation = validate_search_result(results, citations)
    warnings.extend(validation.get("warnings") or [])
    status = SEARCH_STATUS_COMPLETED if validation.get("valid") else SEARCH_STATUS_FAILED
    effective_top_k = int(search_session.get("top_k") or 5)
    result = EnterpriseSearchRuntimeResult(
        search_session_id=search_session.get("search_session_id"),
        search_status=status,
        query=query,
        normalized_query=search_session.get("normalized_query") or normalize_query_text(query),
        organization_id=organization_id,
        total_count=int(fts_search.get("total_count") or len(results)),
        offset=int(fts_search.get("offset") or 0),
        limit=int(fts_search.get("limit") or limit or top_k or 5),
        has_more=bool(fts_search.get("has_more")),
        facets=dict(fts_search.get("facets") or {}),
        results=results,
        citations=citations,
        search_validation=validation,
        blocking_issues=validation.get("blocking_issues") or [],
        warnings=sort_issues(warnings),
        next_available_actions=[
            {
                "action": "generate_answer",
                "available": False,
                "status": "blocked",
                "reason": "llm_answer_generation_not_in_search_foundation_scope",
            }
        ],
    )
    payload = {
        **serialize_enterprise_search_result(result),
        "search_gateway": gateway,
        "knowledge_fts": fts_search,
        "filters": search_filters,
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": bool(fts_search.get("fts_search_succeeded")),
    }
    if knowledge_index_gate is not None:
        payload["knowledge_index_evidence_gate"] = knowledge_index_gate
    if persist_snapshot and db is not None and organization_id is not None:
        payload["runtime_persistence"] = persist_enterprise_search_result(
            db,
            organization_id=organization_id,
            query=query,
            offset=int(payload.get("offset") or 0),
            limit=int(payload.get("limit") or 5),
            top_k=effective_top_k,
            filters=search_filters,
            include_facets=include_facets,
            include_debug=include_debug,
            result=payload,
        )
    return payload
