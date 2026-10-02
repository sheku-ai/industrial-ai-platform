"""Executable Runtime Persistence Runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.documents import Artifact
from app.models.runtime import RuntimePersistenceRecord
from app.repositories.runtime import RuntimePersistenceRecordRepository
from app.services.runtime_persistence_gateway import (
    RuntimePersistenceRecordDescriptor,
    build_runtime_persistence_gateway,
    build_runtime_persistence_records,
    sanitize_for_jsonb,
)

RUNTIME_PERSISTENCE_SCHEMA_VERSION = "1"
PERSISTENCE_STATUS_BLOCKED = "blocked"
PERSISTENCE_STATUS_COMPLETED = "completed"
PERSISTENCE_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class RuntimePersistenceResult:
    execution_id: str | None
    artifact_id: str | None
    persistence_status: str
    records_persisted: int
    persisted_records: list[dict[str, Any]] = field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_available_actions: list[dict[str, Any]] = field(default_factory=list)


def _artifact_organization_id(db: Session, artifact_id: str | None) -> str | None:
    if not artifact_id:
        return None
    try:
        artifact_uuid = uuid.UUID(str(artifact_id))
    except (TypeError, ValueError):
        return None
    artifact = db.get(Artifact, artifact_uuid)
    if artifact is None or artifact.organization_id is None:
        return None
    return str(artifact.organization_id)


def _record_to_model(
    execution_id: str,
    descriptor: RuntimePersistenceRecordDescriptor,
    *,
    artifact_organization_id: str | None,
) -> RuntimePersistenceRecord:
    now = datetime.now(UTC)
    payload = dict(descriptor.payload or {})
    if (
        descriptor.runtime_domain == "knowledge_publication"
        and artifact_organization_id
        and not payload.get("organization_id")
    ):
        payload["organization_id"] = artifact_organization_id
    return RuntimePersistenceRecord(
        execution_id=execution_id,
        runtime_domain=descriptor.runtime_domain,
        record_type=descriptor.record_type,
        record_key=descriptor.record_key,
        artifact_id=descriptor.artifact_id,
        processing_session_id=descriptor.processing_session_id,
        correlation_id=descriptor.correlation_id,
        provider=descriptor.provider,
        execution_status=descriptor.execution_status,
        content_hash=descriptor.content_hash,
        summary=descriptor.summary,
        payload=payload,
        validation=descriptor.validation,
        metrics=descriptor.metrics,
        persistence_status="persisted",
        occurred_at=now,
    )


def _model_to_dict(record: RuntimePersistenceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "execution_id": record.execution_id,
        "runtime_domain": record.runtime_domain,
        "record_type": record.record_type,
        "record_key": record.record_key,
        "artifact_id": record.artifact_id,
        "processing_session_id": record.processing_session_id,
        "correlation_id": record.correlation_id,
        "provider": record.provider,
        "execution_status": record.execution_status,
        "content_hash": record.content_hash,
        "summary": sanitize_for_jsonb(record.summary or {}),
        "payload": sanitize_for_jsonb(record.payload or {}),
        "validation": sanitize_for_jsonb(record.validation or {}),
        "metrics": sanitize_for_jsonb(record.metrics or {}),
        "persistence_status": record.persistence_status,
        "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
        "persisted_at": record.persisted_at.isoformat() if record.persisted_at else None,
    }


def serialize_runtime_persistence_result(result: RuntimePersistenceResult) -> dict[str, Any]:
    completed = result.persistence_status == PERSISTENCE_STATUS_COMPLETED
    return {
        "runtime_persistence_schema_version": RUNTIME_PERSISTENCE_SCHEMA_VERSION,
        "execution_id": result.execution_id,
        "artifact_id": result.artifact_id,
        "persistence_status": result.persistence_status,
        "persistence_completed": completed,
        "persistence_succeeded": completed,
        "records_persisted": result.records_persisted,
        "persisted_records": list(result.persisted_records),
        "blocking_issues": list(result.blocking_issues),
        "warnings": list(result.warnings),
        "next_available_actions": list(result.next_available_actions),
    }


def persist_runtime_outputs(
    db: Session,
    *,
    execution_id: str,
    artifact_id: str | None,
    runtime_outputs: dict[str, Any],
) -> dict[str, Any]:
    gateway = build_runtime_persistence_gateway(
        execution_id=execution_id,
        artifact_id=artifact_id,
        runtime_outputs=runtime_outputs,
    )
    if gateway.get("blocking_issues"):
        result = RuntimePersistenceResult(
            execution_id=execution_id,
            artifact_id=artifact_id,
            persistence_status=PERSISTENCE_STATUS_BLOCKED,
            records_persisted=0,
            blocking_issues=gateway.get("blocking_issues") or [],
            warnings=gateway.get("warnings") or [],
            next_available_actions=gateway.get("next_available_actions") or [],
        )
        return {**serialize_runtime_persistence_result(result), "persistence_gateway": gateway}

    repository = RuntimePersistenceRecordRepository(db)
    descriptors = build_runtime_persistence_records(
        execution_id=execution_id,
        artifact_id=artifact_id,
        runtime_outputs=runtime_outputs,
    )
    artifact_organization_id = _artifact_organization_id(db, artifact_id)
    persisted: list[RuntimePersistenceRecord] = []
    try:
        for descriptor in descriptors:
            persisted.append(
                repository.upsert(
                    _record_to_model(
                        execution_id,
                        descriptor,
                        artifact_organization_id=artifact_organization_id,
                    )
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = RuntimePersistenceResult(
        execution_id=execution_id,
        artifact_id=artifact_id,
        persistence_status=PERSISTENCE_STATUS_COMPLETED,
        records_persisted=len(persisted),
        persisted_records=[_model_to_dict(record) for record in persisted],
        warnings=gateway.get("warnings") or [],
        next_available_actions=[
            {
                "action": "inspect_runtime_persistence",
                "available": True,
                "status": "ready",
                "endpoint": f"/api/runtime/persistence/{execution_id}",
            }
        ],
    )
    return {**serialize_runtime_persistence_result(result), "persistence_gateway": gateway}


def read_runtime_persistence(db: Session, *, execution_id: str) -> dict[str, Any]:
    records = RuntimePersistenceRecordRepository(db).list_by_execution(execution_id)
    domains: dict[str, int] = {}
    for record in records:
        domains[record.runtime_domain] = domains.get(record.runtime_domain, 0) + 1
    return {
        "runtime_persistence_read_schema_version": "1",
        "execution_id": execution_id,
        "record_count": len(records),
        "domains": domains,
        "records": [_model_to_dict(record) for record in records],
        "persistence_status": "persisted" if records else "not_found",
    }
