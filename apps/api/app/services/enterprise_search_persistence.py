from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.enterprise_search_session import normalize_query_text
from app.services.runtime_persistence_runtime import persist_runtime_outputs

ENTERPRISE_SEARCH_EXECUTION_ID_PREFIX = "enterprise-search"


def _canonical_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in sorted((filters or {}).items(), key=lambda item: str(item[0]))
        if value is not None
    }


def build_enterprise_search_execution_id(
    *,
    organization_id: uuid.UUID | str,
    query: str,
    offset: int,
    limit: int,
    top_k: int,
    filters: dict[str, Any] | None,
    include_facets: bool,
    include_debug: bool,
) -> str:
    identity = {
        "organization_id": str(organization_id),
        "normalized_query": normalize_query_text(query),
        "offset": int(offset),
        "limit": int(limit),
        "top_k": int(top_k),
        "filters": _canonical_filters(filters),
        "include_facets": bool(include_facets),
        "include_debug": bool(include_debug),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"{ENTERPRISE_SEARCH_EXECUTION_ID_PREFIX}:{digest}"


def _result_identity(result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        result.get("search_result_id"),
        result.get("rank"),
        result.get("organization_id"),
        result.get("knowledge_document_id"),
        result.get("knowledge_chunk_id"),
        result.get("published_chunk_id"),
        result.get("content_hash"),
        result.get("score"),
    )


def _citation_identity(citation: dict[str, Any]) -> tuple[Any, ...]:
    return (
        citation.get("citation_id"),
        citation.get("organization_id"),
        citation.get("knowledge_document_id"),
        citation.get("knowledge_chunk_id"),
        citation.get("published_chunk_id"),
        citation.get("content_hash"),
    )


def _verify_authoritative_postgresql_result(
    db: Session,
    *,
    query: str,
    offset: int,
    limit: int,
    top_k: int,
    filters: dict[str, Any] | None,
    include_facets: bool,
    include_debug: bool,
    result: dict[str, Any],
) -> None:
    from app.services.knowledge_fts_runtime import build_knowledge_fts_search

    authoritative = build_knowledge_fts_search(
        db,
        query=query,
        top_k=top_k,
        offset=offset,
        limit=limit,
        filters=dict(filters or {}),
        include_facets=include_facets,
        include_debug=include_debug,
        persist_snapshot=False,
    )
    if authoritative.get("fts_search_status") != "completed" or authoritative.get("fts_search_succeeded") is not True:
        raise ValueError("Enterprise Search persistence requires completed PostgreSQL FTS evidence")

    expected_results = result.get("results") if isinstance(result.get("results"), list) else []
    actual_results = authoritative.get("results") if isinstance(authoritative.get("results"), list) else []
    expected_citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    actual_citations = authoritative.get("citations") if isinstance(authoritative.get("citations"), list) else []

    if int(result.get("total_count") or 0) != int(authoritative.get("total_count") or 0):
        raise ValueError("Enterprise Search persisted total_count does not match PostgreSQL FTS evidence")
    if len(expected_results) != len(actual_results):
        raise ValueError("Enterprise Search persisted result_count does not match PostgreSQL FTS evidence")
    if len(expected_citations) != len(actual_citations):
        raise ValueError("Enterprise Search persisted citation count does not match PostgreSQL FTS evidence")

    if [_result_identity(item) for item in expected_results] != [_result_identity(item) for item in actual_results]:
        raise ValueError("Enterprise Search persisted result order or lineage does not match PostgreSQL FTS evidence")
    if [_citation_identity(item) for item in expected_citations] != [
        _citation_identity(item) for item in actual_citations
    ]:
        raise ValueError("Enterprise Search persisted citations do not match PostgreSQL FTS evidence")


def persist_enterprise_search_result(
    db: Session,
    *,
    organization_id: uuid.UUID | str,
    query: str,
    offset: int,
    limit: int,
    top_k: int,
    filters: dict[str, Any] | None,
    include_facets: bool,
    include_debug: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    scoped_filters = dict(filters or {})
    scoped_filters["organization_id"] = str(organization_id)
    _verify_authoritative_postgresql_result(
        db,
        query=query,
        offset=offset,
        limit=limit,
        top_k=top_k,
        filters=scoped_filters,
        include_facets=include_facets,
        include_debug=include_debug,
        result=result,
    )
    execution_id = build_enterprise_search_execution_id(
        organization_id=organization_id,
        query=query,
        offset=offset,
        limit=limit,
        top_k=top_k,
        filters=scoped_filters,
        include_facets=include_facets,
        include_debug=include_debug,
    )
    results = result.get("results") if isinstance(result.get("results"), list) else []
    artifact_id = results[0].get("artifact_id") if results and isinstance(results[0], dict) else None
    return persist_runtime_outputs(
        db,
        execution_id=execution_id,
        artifact_id=artifact_id,
        runtime_outputs={"enterprise_search": result},
    )
