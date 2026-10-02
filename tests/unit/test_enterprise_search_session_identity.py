from __future__ import annotations

import uuid

from app.services.enterprise_search_session import build_enterprise_search_session


def _session_id(*, organization_id: uuid.UUID, filters: dict[str, object] | None = None) -> str | None:
    session = build_enterprise_search_session(
        query="  Inspection   Report ",
        top_k=10,
        indexed_chunk_count=1,
        search_config={
            "filters": filters or {"organization_id": str(organization_id), "status": "indexed"},
            "include_facets": True,
            "include_debug": False,
        },
    )
    return session.search_session_id


def test_enterprise_search_session_identity_is_deterministic() -> None:
    organization_id = uuid.uuid4()

    first = _session_id(
        organization_id=organization_id,
        filters={"organization_id": str(organization_id), "status": "indexed", "artifact_id": None},
    )
    second = build_enterprise_search_session(
        query="inspection report",
        top_k=10,
        indexed_chunk_count=99,
        search_config={
            "filters": {"artifact_id": None, "status": "indexed", "organization_id": str(organization_id)},
            "include_facets": True,
            "include_debug": False,
        },
    ).search_session_id

    assert first == second


def test_enterprise_search_session_identity_is_tenant_scoped() -> None:
    first = _session_id(organization_id=uuid.uuid4())
    second = _session_id(organization_id=uuid.uuid4())

    assert first != second


def test_enterprise_search_session_identity_changes_with_filters() -> None:
    organization_id = uuid.uuid4()

    unfiltered = _session_id(organization_id=organization_id)
    filtered = _session_id(
        organization_id=organization_id,
        filters={
            "organization_id": str(organization_id),
            "status": "indexed",
            "artifact_id": "artifact-1",
        },
    )

    assert unfiltered != filtered


def test_enterprise_search_session_identity_changes_with_response_shape() -> None:
    organization_id = uuid.uuid4()
    base = build_enterprise_search_session(
        query="inspection report",
        top_k=10,
        indexed_chunk_count=1,
        search_config={
            "filters": {"organization_id": str(organization_id)},
            "include_facets": False,
            "include_debug": False,
        },
    ).search_session_id
    with_facets = build_enterprise_search_session(
        query="inspection report",
        top_k=10,
        indexed_chunk_count=1,
        search_config={
            "filters": {"organization_id": str(organization_id)},
            "include_facets": True,
            "include_debug": False,
        },
    ).search_session_id

    assert base != with_facets
