from __future__ import annotations

import uuid
from typing import Any

from app.contracts.enterprise_search import EnterpriseSearchEvidenceV1
from app.models.runtime import RuntimePersistenceRecord


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"persisted Enterprise Search payload requires string field {key!r}")
    return value


def _required_integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"persisted Enterprise Search payload requires integer field {key!r}")
    return value


def _required_boolean(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"persisted Enterprise Search payload requires boolean field {key!r}")
    return value


def _validate_authoritative_completion(record: RuntimePersistenceRecord, payload: dict[str, Any]) -> None:
    if record.persistence_status != "persisted":
        raise ValueError("Enterprise Search evidence requires persistence_status=persisted")
    if record.execution_status != "completed":
        raise ValueError("Enterprise Search evidence requires execution_status=completed")
    if payload.get("search_status") != "completed" or payload.get("search_completed") is not True:
        raise ValueError("Enterprise Search evidence requires a completed persisted search result")

    validation = dict(record.validation or {})
    if validation.get("valid") is not True or validation.get("validation_status") != "valid":
        raise ValueError("Enterprise Search evidence requires valid persisted search validation")

    if payload.get("search_uses_postgresql") is not True or payload.get("search_uses_postgresql_fts") is not True:
        raise ValueError("Enterprise Search evidence requires PostgreSQL FTS execution evidence")
    if (
        payload.get("semantic_search_used") is not False
        or payload.get("embeddings_required") is not False
        or payload.get("ai_required") is not False
    ):
        raise ValueError("Enterprise Search evidence requires non-AI lexical execution flags")


def project_enterprise_search_evidence_v1(
    record: RuntimePersistenceRecord,
    *,
    organization_id: uuid.UUID,
) -> EnterpriseSearchEvidenceV1:
    """Project persisted Enterprise Search evidence into the canonical v1 contract.

    The projection accepts only a completed, persisted ``search_result_set``
    record with valid PostgreSQL FTS evidence. Organization scope is read from
    the PostgreSQL JSONB payload and validated before the evidence crosses the
    runtime boundary. Transient completion flags cannot substitute for the
    persisted record state and validation evidence.
    """

    if record.runtime_domain != "enterprise_search" or record.record_type != "search_result_set":
        raise ValueError("Enterprise Search evidence requires an enterprise_search/search_result_set record")

    payload = dict(record.payload or {})
    persisted_organization_id = payload.get("organization_id")
    try:
        payload_organization_id = uuid.UUID(str(persisted_organization_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("persisted Enterprise Search payload requires a valid organization_id") from exc

    if payload_organization_id != organization_id:
        raise ValueError("persisted Enterprise Search evidence does not match requested organization scope")

    _validate_authoritative_completion(record, payload)

    search_session_id = payload.get("search_session_id")
    if search_session_id is not None and not isinstance(search_session_id, str):
        raise ValueError("persisted Enterprise Search payload search_session_id must be a string or null")

    ranking_model = payload.get("ranking_model")
    if ranking_model is not None and not isinstance(ranking_model, str):
        raise ValueError("persisted Enterprise Search payload ranking_model must be a string or null")

    total_count = _required_integer(payload, "total_count")
    result_count = _required_integer(payload, "result_count")
    offset = _required_integer(payload, "offset")
    limit = _required_integer(payload, "limit")
    if total_count < 0 or result_count < 0 or result_count > total_count:
        raise ValueError("persisted Enterprise Search result counts are inconsistent")
    if offset < 0 or limit < 1:
        raise ValueError("persisted Enterprise Search pagination evidence is invalid")

    return EnterpriseSearchEvidenceV1(
        evidence_id=record.id,
        organization_id=payload_organization_id,
        execution_id=record.execution_id,
        search_session_id=search_session_id,
        query=_required_string(payload, "query"),
        normalized_query=_required_string(payload, "normalized_query"),
        search_status=_required_string(payload, "search_status"),
        ranking_model=ranking_model,
        total_count=total_count,
        result_count=result_count,
        offset=offset,
        limit=limit,
        has_more=_required_boolean(payload, "has_more"),
        search_uses_postgresql=_required_boolean(payload, "search_uses_postgresql"),
        search_uses_postgresql_fts=_required_boolean(payload, "search_uses_postgresql_fts"),
        semantic_search_used=_required_boolean(payload, "semantic_search_used"),
        embeddings_required=_required_boolean(payload, "embeddings_required"),
        ai_required=_required_boolean(payload, "ai_required"),
        persistence_status=record.persistence_status,
        occurred_at=record.occurred_at,
        persisted_at=record.persisted_at,
        payload=payload,
    )
