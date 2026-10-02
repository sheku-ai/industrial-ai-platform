from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.services import knowledge_fts_runtime
from app.services.enterprise_search_persistence import (
    _verify_authoritative_postgresql_result,
    build_enterprise_search_execution_id,
)


def _execution_id(*, organization_id: uuid.UUID, filters: dict[str, object] | None = None) -> str:
    return build_enterprise_search_execution_id(
        organization_id=organization_id,
        query="  Inspection   Report ",
        offset=0,
        limit=10,
        top_k=10,
        filters=filters or {"status": "indexed"},
        include_facets=True,
        include_debug=False,
    )


def _search_payload(organization_id: uuid.UUID) -> dict[str, object]:
    result = {
        "search_result_id": "search-result-1",
        "rank": 1,
        "organization_id": str(organization_id),
        "knowledge_document_id": "document-1",
        "knowledge_chunk_id": "chunk-1",
        "published_chunk_id": "published-1",
        "content_hash": "hash-1",
        "score": 0.75,
    }
    citation = {
        "citation_id": "citation-1",
        "organization_id": str(organization_id),
        "knowledge_document_id": "document-1",
        "knowledge_chunk_id": "chunk-1",
        "published_chunk_id": "published-1",
        "content_hash": "hash-1",
    }
    return {
        "total_count": 1,
        "results": [result],
        "citations": [citation],
    }


def test_enterprise_search_execution_identity_is_deterministic() -> None:
    organization_id = uuid.uuid4()

    first = _execution_id(
        organization_id=organization_id,
        filters={"status": "indexed", "artifact_id": None},
    )
    second = build_enterprise_search_execution_id(
        organization_id=organization_id,
        query="inspection report",
        offset=0,
        limit=10,
        top_k=10,
        filters={"artifact_id": None, "status": "indexed"},
        include_facets=True,
        include_debug=False,
    )

    assert first == second


def test_enterprise_search_execution_identity_is_tenant_scoped() -> None:
    first = _execution_id(organization_id=uuid.uuid4())
    second = _execution_id(organization_id=uuid.uuid4())

    assert first != second


def test_enterprise_search_execution_identity_changes_with_search_scope() -> None:
    organization_id = uuid.uuid4()

    unfiltered = _execution_id(organization_id=organization_id)
    filtered = _execution_id(
        organization_id=organization_id,
        filters={"status": "indexed", "artifact_id": "artifact-1"},
    )

    assert unfiltered != filtered


def test_enterprise_search_execution_identity_changes_with_pagination_or_top_k() -> None:
    organization_id = uuid.uuid4()
    base = _execution_id(organization_id=organization_id)

    different_limit = build_enterprise_search_execution_id(
        organization_id=organization_id,
        query="inspection report",
        offset=0,
        limit=20,
        top_k=10,
        filters={"status": "indexed"},
        include_facets=True,
        include_debug=False,
    )
    different_top_k = build_enterprise_search_execution_id(
        organization_id=organization_id,
        query="inspection report",
        offset=0,
        limit=10,
        top_k=20,
        filters={"status": "indexed"},
        include_facets=True,
        include_debug=False,
    )

    assert base != different_limit
    assert base != different_top_k


def test_enterprise_search_persistence_accepts_matching_postgresql_fts_evidence(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    payload = _search_payload(organization_id)
    authoritative = {
        **payload,
        "fts_search_status": "completed",
        "fts_search_succeeded": True,
    }
    monkeypatch.setattr(knowledge_fts_runtime, "build_knowledge_fts_search", lambda *args, **kwargs: authoritative)

    _verify_authoritative_postgresql_result(
        MagicMock(spec=Session),
        query="inspection report",
        offset=0,
        limit=10,
        top_k=10,
        filters={"organization_id": str(organization_id)},
        include_facets=False,
        include_debug=False,
        result=payload,
    )


def test_enterprise_search_persistence_rejects_ranking_or_lineage_drift(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    payload = _search_payload(organization_id)
    drifted = _search_payload(organization_id)
    drifted["results"][0]["knowledge_chunk_id"] = "chunk-other"  # type: ignore[index]
    authoritative = {
        **drifted,
        "fts_search_status": "completed",
        "fts_search_succeeded": True,
    }
    monkeypatch.setattr(knowledge_fts_runtime, "build_knowledge_fts_search", lambda *args, **kwargs: authoritative)

    with pytest.raises(ValueError, match="result order or lineage"):
        _verify_authoritative_postgresql_result(
            MagicMock(spec=Session),
            query="inspection report",
            offset=0,
            limit=10,
            top_k=10,
            filters={"organization_id": str(organization_id)},
            include_facets=False,
            include_debug=False,
            result=payload,
        )
