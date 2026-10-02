from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.runtime import RuntimePersistenceRecord
from app.services.enterprise_search_evidence_reader import read_enterprise_search_evidence_v1


def _result_payloads(organization_id: uuid.UUID) -> list[dict[str, object]]:
    return [
        {
            "search_result_id": f"search-result-{index}",
            "organization_id": str(organization_id),
            "content_hash": f"content-hash-{index}",
        }
        for index in range(3)
    ]


def _citation_payloads(organization_id: uuid.UUID) -> list[dict[str, object]]:
    return [
        {
            "citation_id": f"citation-{index}",
            "organization_id": str(organization_id),
            "content_hash": f"content-hash-{index}",
        }
        for index in range(3)
    ]


def _record(*, organization_id: uuid.UUID, evidence_id: uuid.UUID | None = None) -> RuntimePersistenceRecord:
    now = datetime.now(UTC)
    return RuntimePersistenceRecord(
        id=evidence_id or uuid.uuid4(),
        execution_id="enterprise-search:0123456789abcdef01234567",
        runtime_domain="enterprise_search",
        record_type="search_result_set",
        record_key="search-session-1",
        artifact_id=None,
        processing_session_id=None,
        correlation_id=None,
        provider=None,
        execution_status="completed",
        content_hash=None,
        summary={},
        payload={
            "organization_id": str(organization_id),
            "search_session_id": "search-session-1",
            "query": "gearbox vibration",
            "normalized_query": "gearbox vibration",
            "search_status": "completed",
            "search_completed": True,
            "ranking_model": "postgres_ts_rank_cd_simple_v1",
            "total_count": 3,
            "result_count": 3,
            "offset": 0,
            "limit": 5,
            "has_more": False,
            "results": _result_payloads(organization_id),
            "citations": _citation_payloads(organization_id),
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
            "semantic_search_used": False,
            "embeddings_required": False,
            "ai_required": False,
        },
        validation={"validation_status": "valid", "valid": True},
        metrics={},
        persistence_status="persisted",
        occurred_at=now,
        persisted_at=now,
        created_at=now,
        updated_at=now,
    )


def _child_records(record: RuntimePersistenceRecord, organization_id: uuid.UUID) -> list[RuntimePersistenceRecord]:
    now = datetime.now(UTC)
    children: list[RuntimePersistenceRecord] = []
    for result in _result_payloads(organization_id):
        children.append(
            RuntimePersistenceRecord(
                id=uuid.uuid4(),
                execution_id=record.execution_id,
                runtime_domain="enterprise_search",
                record_type="search_result",
                record_key=str(result["search_result_id"]),
                execution_status="completed",
                content_hash=str(result["content_hash"]),
                summary={},
                payload=result,
                validation={},
                metrics={},
                persistence_status="persisted",
                occurred_at=now,
                persisted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    for citation in _citation_payloads(organization_id):
        children.append(
            RuntimePersistenceRecord(
                id=uuid.uuid4(),
                execution_id=record.execution_id,
                runtime_domain="enterprise_search",
                record_type="citation",
                record_key=str(citation["citation_id"]),
                execution_status="completed",
                content_hash=str(citation["content_hash"]),
                summary={},
                payload=citation,
                validation={},
                metrics={},
                persistence_status="persisted",
                occurred_at=now,
                persisted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    return children


def _session(record: RuntimePersistenceRecord, organization_id: uuid.UUID) -> MagicMock:
    session = MagicMock(spec=Session)
    session.scalar.return_value = record
    session.scalars.return_value.all.return_value = _child_records(record, organization_id)
    return session


def _read(record: RuntimePersistenceRecord, organization_id: uuid.UUID):
    return read_enterprise_search_evidence_v1(
        _session(record, organization_id),
        organization_id=organization_id,
        evidence_id=record.id,
    )


def test_enterprise_search_evidence_reader_projects_scoped_persisted_record() -> None:
    organization_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    record = _record(organization_id=organization_id, evidence_id=evidence_id)
    session = _session(record, organization_id)

    evidence = read_enterprise_search_evidence_v1(
        session,
        organization_id=organization_id,
        evidence_id=evidence_id,
    )

    assert evidence is not None
    assert evidence.evidence_id == evidence_id
    assert evidence.organization_id == organization_id
    assert evidence.search_status == "completed"
    assert evidence.result_count == 3
    assert evidence.search_uses_postgresql is True
    assert evidence.search_uses_postgresql_fts is True
    assert evidence.semantic_search_used is False
    assert evidence.embeddings_required is False
    assert evidence.ai_required is False

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "runtime.persistence_records.id" in compiled
    assert "runtime.persistence_records.runtime_domain" in compiled
    assert "runtime.persistence_records.record_type" in compiled
    assert "organization_id" in compiled
    assert evidence_id.hex in compiled
    assert "enterprise_search" in compiled
    assert "search_result_set" in compiled
    assert str(organization_id) in compiled

    children_statement = session.scalars.call_args.args[0]
    children_compiled = str(children_statement.compile(compile_kwargs={"literal_binds": True}))
    assert record.execution_id in children_compiled
    assert "search_result" in children_compiled
    assert "citation" in children_compiled


def test_enterprise_search_evidence_reader_returns_none_without_scoped_record() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    evidence = read_enterprise_search_evidence_v1(
        session,
        organization_id=uuid.uuid4(),
        evidence_id=uuid.uuid4(),
    )

    assert evidence is None
    session.scalars.assert_not_called()


def test_enterprise_search_evidence_reader_rejects_record_from_other_organization() -> None:
    requested_organization_id = uuid.uuid4()
    persisted_organization_id = uuid.uuid4()
    record = _record(organization_id=persisted_organization_id)
    session = _session(record, persisted_organization_id)

    with pytest.raises(ValueError, match="does not match requested organization scope"):
        read_enterprise_search_evidence_v1(
            session,
            organization_id=requested_organization_id,
            evidence_id=record.id,
        )


def test_enterprise_search_evidence_reader_rejects_noncanonical_record_type() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.record_type = "search_session"

    with pytest.raises(ValueError, match="enterprise_search/search_result_set"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_nonpersisted_record() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.persistence_status = "not_persisted"

    with pytest.raises(ValueError, match="persistence_status=persisted"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_noncompleted_execution() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.execution_status = "failed"

    with pytest.raises(ValueError, match="execution_status=completed"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_payload_completion_flag_without_completed_status() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.payload = {**record.payload, "search_status": "failed", "search_completed": True}

    with pytest.raises(ValueError, match="completed persisted search result"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_invalid_persisted_validation() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.validation = {"validation_status": "blocked", "valid": False}

    with pytest.raises(ValueError, match="valid persisted search validation"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_non_postgresql_fts_claim() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.payload = {**record.payload, "search_uses_postgresql_fts": False}

    with pytest.raises(ValueError, match="PostgreSQL FTS execution evidence"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_ai_flags() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.payload = {**record.payload, "semantic_search_used": True}

    with pytest.raises(ValueError, match="non-AI lexical execution flags"):
        _read(record, organization_id)


def test_enterprise_search_evidence_reader_rejects_missing_result_row() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    session = _session(record, organization_id)
    session.scalars.return_value.all.return_value = _child_records(record, organization_id)[1:]

    with pytest.raises(ValueError, match="result evidence count"):
        read_enterprise_search_evidence_v1(
            session,
            organization_id=organization_id,
            evidence_id=record.id,
        )


def test_enterprise_search_evidence_reader_rejects_cross_organization_child_row() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    children = _child_records(record, organization_id)
    children[0].payload = {**children[0].payload, "organization_id": str(uuid.uuid4())}
    session = _session(record, organization_id)
    session.scalars.return_value.all.return_value = children

    with pytest.raises(ValueError, match="does not match requested organization scope"):
        read_enterprise_search_evidence_v1(
            session,
            organization_id=organization_id,
            evidence_id=record.id,
        )


def test_enterprise_search_evidence_reader_rejects_result_hash_mismatch() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    children = _child_records(record, organization_id)
    children[0].content_hash = "different-hash"
    session = _session(record, organization_id)
    session.scalars.return_value.all.return_value = children

    with pytest.raises(ValueError, match="content_hash does not match"):
        read_enterprise_search_evidence_v1(
            session,
            organization_id=organization_id,
            evidence_id=record.id,
        )


def test_enterprise_search_evidence_reader_rejects_declared_count_without_payload_evidence() -> None:
    organization_id = uuid.uuid4()
    record = _record(organization_id=organization_id)
    record.payload = {**record.payload, "results": [], "citations": []}

    with pytest.raises(ValueError, match="result payload count"):
        _read(record, organization_id)
