from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recovery import RecoveryEvidence
from app.schemas.recovery_provider_execution import (
    ProviderExecutionEvidenceCreate,
    ProviderExecutionEvidenceRead,
)
from app.services.recovery_resource_identity import is_canonical_resource_type, normalize_resource_type

EVIDENCE_TYPE = "provider_execution_evidence"
SOURCE_ENTITY_TYPE = "provider_execution"
PASSING_EXECUTION_STATUSES = {"completed", "succeeded", "verified"}


def _safe_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_json(item) for item in value]
    return value


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_safe_json(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(token in lowered for token in ("password", "secret", "token", "access_key", "connection")):
            sanitized[key] = "configured"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_payload(item) if isinstance(item, dict) else item for item in value]
        else:
            sanitized[key] = value
    return sanitized


def _validate_scope(payload: ProviderExecutionEvidenceCreate) -> None:
    if payload.scope == "platform" and payload.organization_id is not None:
        raise ValueError("provider_evidence_platform_scope_must_not_have_organization")
    if payload.scope == "organization" and payload.organization_id is None:
        raise ValueError("provider_evidence_organization_scope_requires_organization")


def _source_entity_id(payload: ProviderExecutionEvidenceCreate, resource_type: str) -> str:
    return _stable_hash(
        {
            "scope": payload.scope,
            "organization_id": payload.organization_id,
            "operation": payload.operation,
            "resource_type": resource_type,
            "execution_entity_id": payload.execution_entity_id,
            "idempotency_key": payload.idempotency_key,
        }
    )


def _evidence_payload(payload: ProviderExecutionEvidenceCreate, resource_type: str) -> dict[str, Any]:
    return _safe_json(
        {
            "operation": payload.operation,
            "resource_type": resource_type,
            "execution_entity_id": payload.execution_entity_id,
            "provider_type": payload.provider_type,
            "provider_execution_id": payload.provider_execution_id,
            "execution_status": payload.execution_status,
            "started_at": payload.started_at,
            "completed_at": payload.completed_at,
            "evidence_source": payload.evidence_source,
            "correlation_id": payload.correlation_id,
            "idempotency_key": payload.idempotency_key,
            "reference_payload": _sanitize_payload(payload.reference_payload),
        }
    )


def _read(evidence: RecoveryEvidence) -> ProviderExecutionEvidenceRead:
    payload = evidence.evidence_payload
    return ProviderExecutionEvidenceRead(
        id=evidence.id,
        scope=evidence.scope,
        organization_id=evidence.organization_id,
        operation=str(payload["operation"]),
        resource_type=str(payload["resource_type"]),
        execution_entity_id=uuid.UUID(str(payload["execution_entity_id"])),
        provider_type=str(payload["provider_type"]),
        provider_execution_id=str(payload["provider_execution_id"]),
        execution_status=str(payload["execution_status"]),
        started_at=datetime.fromisoformat(str(payload["started_at"])),
        completed_at=datetime.fromisoformat(str(payload["completed_at"])),
        observed_at=evidence.observed_at,
        evidence_source=str(payload["evidence_source"]),
        correlation_id=str(payload["correlation_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        evidence_hash=evidence.evidence_hash,
    )


def register_provider_execution_evidence(
    db: Session,
    payload: ProviderExecutionEvidenceCreate,
) -> ProviderExecutionEvidenceRead:
    _validate_scope(payload)
    resource_type = normalize_resource_type(payload.resource_type)
    if not is_canonical_resource_type(resource_type):
        raise ValueError("legacy_recovery_resource_not_authoritative")
    if payload.completed_at < payload.started_at:
        raise ValueError("provider_evidence_completion_precedes_start")

    source_entity_id = _source_entity_id(payload, resource_type)
    evidence_payload = _evidence_payload(payload, resource_type)
    status = "passed" if payload.execution_status in PASSING_EXECUTION_STATUSES else payload.execution_status
    observed_at = payload.observed_at or datetime.now(UTC)
    evidence_hash = _stable_hash(
        {
            "scope": payload.scope,
            "organization_id": payload.organization_id,
            "evidence_type": EVIDENCE_TYPE,
            "source_entity_type": SOURCE_ENTITY_TYPE,
            "source_entity_id": source_entity_id,
            "status": status,
            "payload": evidence_payload,
        }
    )

    existing = db.scalar(
        select(RecoveryEvidence).where(
            RecoveryEvidence.scope == payload.scope,
            RecoveryEvidence.organization_id.is_(None)
            if payload.organization_id is None
            else RecoveryEvidence.organization_id == payload.organization_id,
            RecoveryEvidence.evidence_type == EVIDENCE_TYPE,
            RecoveryEvidence.source_entity_type == SOURCE_ENTITY_TYPE,
            RecoveryEvidence.source_entity_id == source_entity_id,
        )
    )
    if existing is not None:
        if existing.evidence_hash != evidence_hash:
            raise ValueError("provider_evidence_idempotency_conflict")
        return _read(existing)

    evidence = RecoveryEvidence(
        scope=payload.scope,
        organization_id=payload.organization_id,
        evidence_type=EVIDENCE_TYPE,
        source_entity_type=SOURCE_ENTITY_TYPE,
        source_entity_id=source_entity_id,
        status=status,
        evidence_payload=evidence_payload,
        evidence_hash=evidence_hash,
        observed_at=observed_at,
        expires_at=None,
    )
    db.add(evidence)
    db.flush()
    return _read(evidence)


def provider_execution_evidence_for(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    operation: str,
    execution_entity_id: uuid.UUID,
    resource_type: str,
) -> RecoveryEvidence | None:
    canonical_resource = normalize_resource_type(resource_type)
    if not is_canonical_resource_type(canonical_resource):
        return None
    evidence_rows = db.scalars(
        select(RecoveryEvidence)
        .where(
            RecoveryEvidence.scope == scope,
            RecoveryEvidence.organization_id.is_(None)
            if organization_id is None
            else RecoveryEvidence.organization_id == organization_id,
            RecoveryEvidence.evidence_type == EVIDENCE_TYPE,
            RecoveryEvidence.source_entity_type == SOURCE_ENTITY_TYPE,
            RecoveryEvidence.status == "passed",
        )
        .order_by(RecoveryEvidence.observed_at.desc())
    ).all()
    for evidence in evidence_rows:
        payload = evidence.evidence_payload
        if (
            payload.get("operation") == operation
            and payload.get("execution_entity_id") == str(execution_entity_id)
            and payload.get("resource_type") == canonical_resource
        ):
            expected_hash = _stable_hash(
                {
                    "scope": evidence.scope,
                    "organization_id": evidence.organization_id,
                    "evidence_type": evidence.evidence_type,
                    "source_entity_type": evidence.source_entity_type,
                    "source_entity_id": evidence.source_entity_id,
                    "status": evidence.status,
                    "payload": evidence.evidence_payload,
                }
            )
            if expected_hash == evidence.evidence_hash:
                return evidence
    return None
