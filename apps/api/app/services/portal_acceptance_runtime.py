from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.portal_acceptance import PORTAL_VALIDATION_TYPES, PortalAcceptanceEvidence
from app.repositories.portal_acceptance import PortalAcceptanceRepository
from app.schemas.portal_acceptance import (
    PortalAcceptanceEvidenceCreate,
    PortalAcceptanceEvidenceRead,
    PortalAcceptanceGateResult,
    PortalAcceptanceLatest,
    PortalAcceptanceReadiness,
)
from app.services.readiness_contract import build_readiness_evidence

PORTAL_GATE_BY_TYPE = {
    "principal_routes": "principal_routes_available",
    "portal_build": "portal_build_validated",
    "portal_contract": "portal_contract_validated",
    "negative_states": "negative_states_validated",
    "permission_states": "permission_states_validated",
    "cross_organization_states": "cross_organization_states_validated",
}


def _now() -> datetime:
    return datetime.now(UTC)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _evidence_input(payload: PortalAcceptanceEvidenceCreate) -> dict[str, Any]:
    return payload.model_dump(mode="json", exclude={"created_by"})


def _stored_evidence_input(evidence: PortalAcceptanceEvidence) -> dict[str, Any]:
    payload = PortalAcceptanceEvidenceCreate.model_construct(
        scope=evidence.scope,
        organization_id=evidence.organization_id,
        validation_run_code=evidence.validation_run_code,
        validation_type=evidence.validation_type,
        status=evidence.status,
        source=evidence.source,
        source_reference=evidence.source_reference,
        evidence_payload=evidence.evidence_payload,
        started_at=evidence.started_at,
        completed_at=evidence.completed_at,
        observed_at=evidence.observed_at,
        expires_at=evidence.expires_at,
        created_by=evidence.created_by,
    )
    return _evidence_input(payload)


def _audit(
    db: Session,
    evidence: PortalAcceptanceEvidence,
    *,
    actor_id: str | None,
) -> None:
    after = {
        "validation_run_code": evidence.validation_run_code,
        "validation_type": evidence.validation_type,
        "status": evidence.status,
        "evidence_hash": evidence.evidence_hash,
        "postgresql_source_of_truth": True,
    }
    db.add(
        AuditEvent(
            organization_id=evidence.organization_id,
            actor_type="service",
            actor_id=actor_id,
            resource_type="runtime.portal_acceptance_evidence",
            resource_id=str(evidence.id),
            summary="portal acceptance evidence registered",
            metadata_json=after,
        )
    )
    db.add(
        AuditHistory(
            organization_id=evidence.organization_id,
            entity_type="runtime.portal_acceptance_evidence",
            entity_id=str(evidence.id),
            action="registered",
            before_state={},
            after_state=after,
            actor_type="service",
            actor_id=actor_id,
        )
    )


def register_portal_evidence(
    db: Session,
    payload: PortalAcceptanceEvidenceCreate,
) -> PortalAcceptanceEvidenceRead:
    repository = PortalAcceptanceRepository(db)
    evidence_input = _evidence_input(payload)
    evidence_hash = stable_hash(evidence_input)
    existing = repository.find_identity(
        payload.scope,
        payload.organization_id,
        payload.validation_run_code,
        payload.validation_type,
    )
    if existing is not None:
        if existing.evidence_hash != evidence_hash:
            raise ValueError("portal_evidence_idempotency_conflict")
        return PortalAcceptanceEvidenceRead.model_validate(existing)
    evidence = repository.add(
        PortalAcceptanceEvidence(
            **payload.model_dump(exclude={"created_by"}),
            evidence_hash=evidence_hash,
            created_by=payload.created_by,
        )
    )
    _audit(db, evidence, actor_id=payload.created_by)
    db.flush()
    return PortalAcceptanceEvidenceRead.model_validate(evidence)


def _status_from_gates(gates: list[PortalAcceptanceGateResult]) -> str:
    statuses = {gate.status for gate in gates}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "not_evaluated" in statuses:
        return "not_evaluated"
    return "passed" if gates and statuses == {"passed"} else "not_evaluated"


def build_portal_acceptance_readiness(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
    validation_run_code: str | None = None,
) -> PortalAcceptanceReadiness:
    repository = PortalAcceptanceRepository(db)
    run_code = validation_run_code or repository.latest_run_code(scope, organization_id)
    evidence = (
        repository.list_evidence(scope, organization_id, validation_run_code=run_code)
        if run_code
        else []
    )
    by_type = {item.validation_type: item for item in evidence}
    now = _now()
    gates: list[PortalAcceptanceGateResult] = []
    blockers: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    for validation_type in PORTAL_VALIDATION_TYPES:
        item = by_type.get(validation_type)
        expired = bool(item and item.expires_at and item.expires_at <= now)
        if item is None:
            status = "not_evaluated"
            summary = f"Persisted {validation_type} evidence is not available for the selected validation run."
        elif expired:
            status = "blocked"
            summary = f"Persisted {validation_type} evidence is expired."
        else:
            status = item.status
            summary = f"Persisted {validation_type} evidence is {status}."
        age = max(0, int((now - item.observed_at).total_seconds())) if item else None
        gate = PortalAcceptanceGateResult(
            gate_code=PORTAL_GATE_BY_TYPE[validation_type],
            validation_type=validation_type,
            status=status,
            summary=summary,
            evidence_reference=str(item.id) if item else None,
            evidence_origin=item.source if item else None,
            observed_at=item.observed_at if item else None,
            evidence_age_seconds=age,
        )
        gates.append(gate)
        if status in {"failed", "blocked"}:
            blockers.append(
                {
                    "code": f"PORTAL_{validation_type.upper()}_{'FAILED' if status == 'failed' else 'BLOCKED'}",
                    "gate_code": gate.gate_code,
                    "message": summary,
                }
            )
        if status != "passed":
            next_actions.append(
                {
                    "action": "register_portal_acceptance_evidence",
                    "validation_type": validation_type,
                    "validation_run_code": run_code,
                }
            )
    ages = [gate.evidence_age_seconds for gate in gates if gate.evidence_age_seconds is not None]
    status = _status_from_gates(gates)
    expirations = [item.expires_at for item in evidence if item.expires_at is not None]
    expired = any(item.expires_at is not None and item.expires_at <= now for item in evidence)
    integrity_errors = [
        {
            "code": "portal_evidence_corrupt",
            "message": "Persisted Portal Acceptance evidence hash does not match its payload.",
            "evidence_id": str(item.id),
        }
        for item in evidence
        if stable_hash(_stored_evidence_input(item)) != item.evidence_hash
    ]
    evidence_contract = build_readiness_evidence(
        domain="portal",
        status="expired" if expired else status,
        gate_results=gates,
        blockers=blockers,
        warnings=[],
        next_actions=next_actions,
        runtime_version="portal-acceptance-runtime.v1",
        evaluation_timestamp=max((item.observed_at for item in evidence), default=None),
        expires_at=min(expirations) if expirations else None,
        evidence_origin="portal_acceptance_runtime",
        components_evaluated=list(PORTAL_VALIDATION_TYPES),
        evidence_ids=[str(item.id) for item in evidence],
        source_runtime_version="portal-acceptance-runtime.v1",
        supported_runtime_versions=("portal-acceptance-runtime.v1",),
        integrity_errors=integrity_errors,
    )
    return PortalAcceptanceReadiness(
        status=evidence_contract.status,
        reason=evidence_contract.reason,
        scope=scope,
        organization_id=organization_id,
        validation_run_code=run_code,
        gate_results=gates,
        blockers=evidence_contract.blockers,
        warnings=evidence_contract.warnings,
        recommendations=evidence_contract.recommendations,
        next_actions=evidence_contract.next_actions,
        components_evaluated=list(PORTAL_VALIDATION_TYPES),
        evidence_origins=sorted({item.source for item in evidence}),
        evidence_references=[str(item.id) for item in evidence],
        evaluated_at=now,
        evaluation_timestamp=evidence_contract.evaluation_timestamp,
        expires_at=evidence_contract.expires_at,
        evidence_age_seconds=max(ages) if ages else None,
        evidence_contract=evidence_contract,
        contract_version=evidence_contract.contract_version,
        runtime_version=evidence_contract.runtime_version,
    )


def latest_portal_acceptance(
    db: Session,
    *,
    scope: str = "platform",
    organization_id: uuid.UUID | None = None,
) -> PortalAcceptanceLatest:
    repository = PortalAcceptanceRepository(db)
    run_code = repository.latest_run_code(scope, organization_id)
    readiness = build_portal_acceptance_readiness(
        db,
        scope=scope,
        organization_id=organization_id,
        validation_run_code=run_code,
    )
    evidence = (
        repository.list_evidence(scope, organization_id, validation_run_code=run_code)
        if run_code
        else []
    )
    return PortalAcceptanceLatest(
        found=bool(run_code),
        validation_run_code=run_code,
        evidence=[PortalAcceptanceEvidenceRead.model_validate(item) for item in evidence],
        readiness=readiness,
    )
