from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.recovery import RecoveryPolicy, RestoreExecution, RestoreVerification
from app.schemas.recovery import RestoreVerificationCompleteRequest, RestoreVerificationRead
from app.services.recovery_runtime import (
    complete_restore_verification as complete_restore_verification_legacy,
)
from app.services.recovery_verification_evidence import (
    REQUIRED_VERIFICATION_CHECKS,
    restore_verification_check_evidence_for,
)


def complete_restore_verification(
    db: Session,
    policy: RecoveryPolicy,
    restore: RestoreExecution,
    verification: RestoreVerification,
    payload: RestoreVerificationCompleteRequest,
) -> RestoreVerificationRead:
    evidence_ids: dict[str, str] = {}
    authoritative_checks: dict[str, bool] = {}

    for check_code in REQUIRED_VERIFICATION_CHECKS:
        evidence = restore_verification_check_evidence_for(
            db,
            scope=restore.scope,
            organization_id=restore.organization_id,
            verification_id=verification.id,
            check_code=check_code,
        )
        if evidence is None:
            raise ValueError(f"{check_code}_evidence_missing")
        evidence_payload = evidence.evidence_payload
        if evidence_payload.get("correlation_id") != restore.correlation_id:
            raise ValueError(f"{check_code}_correlation_mismatch")
        authoritative_checks[check_code] = True
        evidence_ids[check_code] = str(evidence.id)

    authoritative_payload = payload.model_copy(
        update={
            **authoritative_checks,
            "verification_payload": {
                "authoritative_check_evidence": evidence_ids,
                "submitted_context": payload.verification_payload,
            },
        }
    )
    return complete_restore_verification_legacy(
        db,
        policy,
        restore,
        verification,
        authoritative_payload,
    )
