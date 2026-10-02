from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enterprise_search import EnterpriseSearchEvidenceV1
from app.models.runtime import RuntimePersistenceRecord
from app.services.enterprise_search_contract_projection import project_enterprise_search_evidence_v1


def _payload_organization_id(record: RuntimePersistenceRecord) -> uuid.UUID:
    try:
        return uuid.UUID(str((record.payload or {}).get("organization_id")))
    except (TypeError, ValueError) as exc:
        raise ValueError("persisted Enterprise Search child evidence requires a valid organization_id") from exc


def _reconcile_child_evidence(
    *,
    result_set: RuntimePersistenceRecord,
    child_records: list[RuntimePersistenceRecord],
    organization_id: uuid.UUID,
) -> None:
    payload = dict(result_set.payload or {})
    expected_result_count = payload.get("result_count")
    expected_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    expected_citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    persisted_results = [record for record in child_records if record.record_type == "search_result"]
    persisted_citations = [record for record in child_records if record.record_type == "citation"]

    if isinstance(expected_result_count, bool) or not isinstance(expected_result_count, int):
        raise ValueError("persisted Enterprise Search result set requires integer result_count")
    if len(expected_results) != expected_result_count:
        raise ValueError("persisted Enterprise Search result payload count does not match result_count")
    if len(expected_citations) != expected_result_count:
        raise ValueError("persisted Enterprise Search citation payload count does not match result_count")
    if len(persisted_results) != len(expected_results):
        raise ValueError("persisted Enterprise Search result evidence count does not match search_result_set")
    if len(persisted_citations) != len(expected_citations):
        raise ValueError("persisted Enterprise Search citation evidence count does not match search_result_set")

    expected_result_ids = {
        str(item.get("search_result_id")): str(item.get("content_hash") or "")
        for item in expected_results
        if isinstance(item, dict) and item.get("search_result_id")
    }
    expected_citation_ids = {
        str(item.get("citation_id")): str(item.get("content_hash") or "")
        for item in expected_citations
        if isinstance(item, dict) and item.get("citation_id")
    }
    if len(expected_result_ids) != len(expected_results):
        raise ValueError("persisted Enterprise Search result set contains a result without search_result_id")
    if len(expected_citation_ids) != len(expected_citations):
        raise ValueError("persisted Enterprise Search result set contains a citation without citation_id")

    for record in persisted_results:
        if record.execution_status != "completed" or record.persistence_status != "persisted":
            raise ValueError("persisted Enterprise Search result evidence is not completed and persisted")
        if _payload_organization_id(record) != organization_id:
            raise ValueError("persisted Enterprise Search result evidence does not match requested organization scope")
        result_id = str((record.payload or {}).get("search_result_id") or "")
        if result_id not in expected_result_ids:
            raise ValueError("persisted Enterprise Search result evidence does not belong to search_result_set")
        if str(record.content_hash or "") != expected_result_ids[result_id]:
            raise ValueError(
                "persisted Enterprise Search result evidence content_hash does not match search_result_set"
            )

    for record in persisted_citations:
        if record.execution_status != "completed" or record.persistence_status != "persisted":
            raise ValueError("persisted Enterprise Search citation evidence is not completed and persisted")
        if _payload_organization_id(record) != organization_id:
            raise ValueError(
                "persisted Enterprise Search citation evidence does not match requested organization scope"
            )
        citation_id = str((record.payload or {}).get("citation_id") or "")
        if citation_id not in expected_citation_ids:
            raise ValueError("persisted Enterprise Search citation evidence does not belong to search_result_set")
        if str(record.content_hash or "") != expected_citation_ids[citation_id]:
            raise ValueError(
                "persisted Enterprise Search citation evidence content_hash does not match search_result_set"
            )


def read_enterprise_search_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
) -> EnterpriseSearchEvidenceV1 | None:
    """Read organization-scoped Enterprise Search evidence from PostgreSQL.

    Enterprise Search evidence is authoritative only when the persisted
    ``search_result_set`` and its persisted ``search_result``/``citation`` rows
    agree on execution identity, organization scope, counts, IDs and hashes.
    """

    record = session.scalar(
        select(RuntimePersistenceRecord).where(
            RuntimePersistenceRecord.id == evidence_id,
            RuntimePersistenceRecord.runtime_domain == "enterprise_search",
            RuntimePersistenceRecord.record_type == "search_result_set",
            RuntimePersistenceRecord.payload["organization_id"].astext == str(organization_id),
        )
    )
    if record is None:
        return None

    child_records = list(
        session.scalars(
            select(RuntimePersistenceRecord).where(
                RuntimePersistenceRecord.execution_id == record.execution_id,
                RuntimePersistenceRecord.runtime_domain == "enterprise_search",
                RuntimePersistenceRecord.record_type.in_(("search_result", "citation")),
            )
        ).all()
    )
    _reconcile_child_evidence(
        result_set=record,
        child_records=child_records,
        organization_id=organization_id,
    )
    return project_enterprise_search_evidence_v1(record, organization_id=organization_id)
