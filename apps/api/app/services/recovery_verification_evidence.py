from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recovery import RecoveryEvidence
from app.schemas.recovery_verification_evidence import (
    RestoreVerificationCheckEvidenceCreate,
    RestoreVerificationCheckEvidenceRead,
)

EVIDENCE_TYPE = "restore_verification_check_evidence"
SOURCE_ENTITY_TYPE = "restore_verification_check"

REQUIRED_VERIFICATION_CHECKS = (
    "database_connectivity_verified",
    "schema_version_verified",
    "record_counts_verified",
    "object_storage_access_verified",
    "artifact_checksums_verified",
    "organization_isolation_verified",
    "knowledge_lineage_verified",
    "enterprise_search_verified",
    "conversation_persistence_verified",
    "document_registration_verified",
    "assistant_runtime_verified",
    "audit_runtime_verified",
)


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


def _source_entity_id(
    *,
    verification_id: uuid.UUID,
    check_code: str,
    idempotency_key: str,
) -> str:
    return _stable_hash(
        {
            "verification_id": verification_id,
            "check_code": check_code,
            "idempotency_key": idempotency_key,
        }
    )


def _read(evidence: RecoveryEvidence) -> RestoreVerificationCheckEvidenceRead:
    payload = evidence.evidence_payload
    return RestoreVerificationCheckEvidenceRead(
        id=evidence.id,
        scope=evidence.scope,
        organization_id=evidence.organization_id,
        verification_id=uuid.UUID(str(payload["verification_id"])),
        check_code=str(payload["check_code"]),
        check_status=str(payload["check_status"]),
        observed_at=evidence.observed_at,
        evidence_source=str(payload["evidence_source"]),
        correlation_id=str(payload["correlation_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        evidence_hash=evidence.evidence_hash,
    )


def register_restore_verification_check_evidence(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    verification_id: uuid.UUID,
    payload: RestoreVerificationCheckEvidenceCreate,
) -> RestoreVerificationCheckEvidenceRead:
    if payload.check_code not in REQUIRED_VERIFICATION_CHECKS:
        raise ValueError("restore_verification_check_not_supported")

    observed_at = payload.observed_at or datetime.now(UTC)
    source_entity_id = _source_entity_id(
        verification_id=verification_id,
        check_code=payload.check_code,
        idempotency_key=payload.idempotency_key,
    )
    evidence_payload = _safe_json(
        {
            "verification_id": verification_id,
            "check_code": payload.check_code,
            "check_status": payload.check_status,
            "evidence_source": payload.evidence_source,
            "correlation_id": payload.correlation_id,
            "idempotency_key": payload.idempotency_key,
            "reference_payload": _sanitize_payload(payload.reference_payload),
        }
    )
    status = "passed" if payload.check_status == "passed" else "failed"
    evidence_hash = _stable_hash(
        {
            "scope": scope,
            "organization_id": organization_id,
            "evidence_type": EVIDENCE_TYPE,
            "source_entity_type": SOURCE_ENTITY_TYPE,
            "source_entity_id": source_entity_id,
            "status": status,
            "payload": evidence_payload,
        }
    )

    existing = db.scalar(
        select(RecoveryEvidence).where(
            RecoveryEvidence.scope == scope,
            RecoveryEvidence.organization_id.is_(None)
            if organization_id is None
            else RecoveryEvidence.organization_id == organization_id,
            RecoveryEvidence.evidence_type == EVIDENCE_TYPE,
            RecoveryEvidence.source_entity_type == SOURCE_ENTITY_TYPE,
            RecoveryEvidence.source_entity_id == source_entity_id,
        )
    )
    if existing is not None:
        if existing.evidence_hash != evidence_hash:
            raise ValueError("restore_verification_evidence_idempotency_conflict")
        return _read(existing)

    evidence = RecoveryEvidence(
        scope=scope,
        organization_id=organization_id,
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


def restore_verification_check_evidence_for(
    db: Session,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    verification_id: uuid.UUID,
    check_code: str,
) -> RecoveryEvidence | None:
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
        if payload.get("verification_id") != str(verification_id) or payload.get("check_code") != check_code:
            continue
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
