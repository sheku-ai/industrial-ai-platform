from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import (
    get_readiness_runtime_context as get_runtime_context,
)
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.recovery import RecoveryRepository
from app.schemas.recovery_provider_execution import (
    ProviderExecutionEvidenceCreate,
    ProviderExecutionEvidenceRead,
)
from app.schemas.recovery_verification_evidence import (
    RestoreVerificationCheckEvidenceCreate,
    RestoreVerificationCheckEvidenceRead,
)
from app.services.recovery_provider_execution_evidence import (
    register_provider_execution_evidence,
)
from app.services.recovery_verification_evidence import (
    register_restore_verification_check_evidence,
)

router = APIRouter(prefix="/platform/recovery", tags=["platform-recovery"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.recovery", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"recovery {action} permission is required",
        )


def _scope(context: RuntimeRequestContext) -> tuple[str, uuid.UUID | None]:
    if context.scope_type == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="platform authorization scope is required",
            )
        return "platform", None
    if context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization_id is required",
        )
    return "organization", context.organization_id


def _execution_or_404(
    repo: RecoveryRepository,
    payload: ProviderExecutionEvidenceCreate,
    scope: str,
    organization_id: uuid.UUID | None,
):
    if payload.operation == "backup":
        execution = repo.get_backup(payload.execution_entity_id, scope, organization_id)
    else:
        execution = repo.get_restore(payload.execution_entity_id, scope, organization_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="recovery execution not found",
        )
    return execution


@router.post("/provider-execution-evidence", response_model=ProviderExecutionEvidenceRead)
def create_provider_execution_evidence(
    payload: ProviderExecutionEvidenceCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProviderExecutionEvidenceRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    if payload.scope != scope or payload.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="recovery execution not found",
        )

    execution = _execution_or_404(RecoveryRepository(db), payload, scope, organization_id)
    if payload.provider_type != execution.provider_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="provider_execution_provider_mismatch",
        )
    if payload.correlation_id != execution.correlation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="provider_execution_correlation_mismatch",
        )

    try:
        result = register_provider_execution_evidence(
            db,
            payload.model_copy(
                update={
                    "scope": execution.scope,
                    "organization_id": execution.organization_id,
                    "provider_type": execution.provider_type,
                    "correlation_id": execution.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        db.rollback()
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.post(
    "/verifications/{verification_id}/check-evidence",
    response_model=RestoreVerificationCheckEvidenceRead,
)
def create_restore_verification_check_evidence(
    verification_id: uuid.UUID,
    payload: RestoreVerificationCheckEvidenceCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreVerificationCheckEvidenceRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    repo = RecoveryRepository(db)
    verification = repo.get_verification(verification_id)
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="restore verification not found",
        )
    restore = repo.get_restore(verification.restore_execution_id, scope, organization_id)
    if restore is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="restore verification not found",
        )
    if payload.correlation_id != restore.correlation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="verification_evidence_correlation_mismatch",
        )

    try:
        result = register_restore_verification_check_evidence(
            db,
            scope=restore.scope,
            organization_id=restore.organization_id,
            verification_id=verification.id,
            payload=payload.model_copy(update={"correlation_id": restore.correlation_id}),
        )
    except ValueError as exc:
        db.rollback()
        raise runtime_http_error(exc) from exc
    db.commit()
    return result
