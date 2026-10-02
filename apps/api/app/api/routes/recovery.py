from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.recovery import RecoveryRepository
from app.schemas.recovery import (
    BackupArtifactCreate,
    BackupArtifactRead,
    BackupCompleteRequest,
    BackupExecutionCreate,
    BackupExecutionRead,
    RecoveryEvidenceRead,
    RecoveryPolicyCreate,
    RecoveryPolicyRead,
    RecoveryPolicyUpdate,
    RecoveryReadinessResponse,
    RecoveryWorkspaceRuntimeResponse,
    RestoreApproveRequest,
    RestoreCompleteRequest,
    RestoreExecutionCreate,
    RestoreExecutionRead,
    RestoreVerificationCompleteRequest,
    RestoreVerificationCreate,
    RestoreVerificationRead,
    RuntimeFailureRequest,
)
from app.schemas.release_operational_evidence import BackupEvidenceContract
from app.services.recovery_authoritative_completion import (
    complete_backup_execution,
    complete_restore_execution,
)
from app.services.recovery_authoritative_verification import complete_restore_verification
from app.services.recovery_objectives_runtime import (
    build_recovery_readiness,
    build_recovery_workspace_runtime,
)
from app.services.recovery_runtime import (
    activate_recovery_policy,
    add_backup_artifact,
    approve_restore_execution,
    create_recovery_policy,
    create_restore_verification,
    deactivate_recovery_policy,
    fail_backup_execution,
    fail_restore_execution,
    fail_restore_verification,
    register_backup_execution,
    register_restore_execution,
    update_recovery_policy,
)
from app.services.release_operational_evidence_runtime import get_backup_evidence_contract

router = APIRouter(prefix="/platform/recovery", tags=["platform-recovery"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.recovery", action):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"recovery {action} permission is required")


def _scope(
    context: RuntimeRequestContext,
    requested_scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID | None]:
    scope = requested_scope or context.scope_type
    if scope == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="platform authorization scope is required"
            )
        return "platform", None
    resolved_org = organization_id or context.organization_id
    if resolved_org is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery resource not found")
    return "organization", resolved_org


def _policy_or_404(repo: RecoveryRepository, policy_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
    policy = repo.get_policy(policy_id, scope, organization_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery policy not found")
    return policy


def _backup_or_404(repo: RecoveryRepository, backup_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
    backup = repo.get_backup(backup_id, scope, organization_id)
    if backup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup execution not found")
    return backup


def _restore_or_404(repo: RecoveryRepository, restore_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
    restore = repo.get_restore(restore_id, scope, organization_id)
    if restore is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="restore execution not found")
    return restore


@router.post("/policies", response_model=RecoveryPolicyRead)
def create_policy(
    payload: RecoveryPolicyCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RecoveryPolicyRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    result = create_recovery_policy(db, payload.model_copy(update={"scope": scope, "organization_id": organization_id}))
    db.commit()
    return result


@router.get("/policies", response_model=list[RecoveryPolicyRead])
def list_policies(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RecoveryPolicyRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        RecoveryPolicyRead.model_validate(item)
        for item in RecoveryRepository(db).list_policies(resolved_scope, resolved_org)
    ]


@router.get("/policies/{policy_id}", response_model=RecoveryPolicyRead)
def read_policy(
    policy_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> RecoveryPolicyRead:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    return RecoveryPolicyRead.model_validate(
        _policy_or_404(RecoveryRepository(db), policy_id, resolved_scope, resolved_org)
    )


@router.patch("/policies/{policy_id}", response_model=RecoveryPolicyRead)
def patch_policy(
    policy_id: uuid.UUID,
    payload: RecoveryPolicyUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RecoveryPolicyRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    policy = _policy_or_404(RecoveryRepository(db), policy_id, resolved_scope, resolved_org)
    result = update_recovery_policy(db, policy, payload)
    db.commit()
    return result


@router.post("/policies/{policy_id}/activate", response_model=RecoveryPolicyRead)
def activate_policy(
    policy_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> RecoveryPolicyRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    policy = _policy_or_404(RecoveryRepository(db), policy_id, resolved_scope, resolved_org)
    try:
        result = activate_recovery_policy(db, policy)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise runtime_http_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="recovery_policy_activation_conflict",
        ) from exc
    return result


@router.post("/policies/{policy_id}/deactivate", response_model=RecoveryPolicyRead)
def deactivate_policy(
    policy_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> RecoveryPolicyRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    policy = _policy_or_404(RecoveryRepository(db), policy_id, resolved_scope, resolved_org)
    result = deactivate_recovery_policy(db, policy)
    db.commit()
    return result


@router.post("/backups", response_model=BackupExecutionRead)
def create_backup(
    payload: BackupExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BackupExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_backup_execution(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.get("/backups", response_model=list[BackupExecutionRead])
def list_backups(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[BackupExecutionRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        BackupExecutionRead.model_validate(item)
        for item in RecoveryRepository(db).list_backups(resolved_scope, resolved_org)
    ]


@router.get("/backups/{backup_id}", response_model=BackupExecutionRead)
def read_backup(
    backup_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> BackupExecutionRead:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    return BackupExecutionRead.model_validate(
        _backup_or_404(RecoveryRepository(db), backup_id, resolved_scope, resolved_org)
    )


@router.get("/backups/{backup_id}/artifacts", response_model=list[BackupArtifactRead])
def list_backup_artifacts(
    backup_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> list[BackupArtifactRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    repo = RecoveryRepository(db)
    _backup_or_404(repo, backup_id, resolved_scope, resolved_org)
    return [BackupArtifactRead.model_validate(item) for item in repo.artifacts_for_backup(backup_id)]


@router.get("/backups/{backup_id}/operational-evidence", response_model=BackupEvidenceContract)
def read_backup_operational_evidence(
    backup_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BackupEvidenceContract:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    try:
        return get_backup_evidence_contract(
            db,
            backup_id,
            scope=resolved_scope,
            organization_id=resolved_org,
        )
    except ValueError as exc:
        raise runtime_http_error(exc) from exc


@router.post("/backups/{backup_id}/artifacts", response_model=BackupArtifactRead)
def create_backup_artifact(
    backup_id: uuid.UUID,
    payload: BackupArtifactCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BackupArtifactRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    backup = _backup_or_404(RecoveryRepository(db), backup_id, resolved_scope, resolved_org)
    result = add_backup_artifact(db, backup, payload)
    db.commit()
    return result


@router.post("/backups/{backup_id}/complete", response_model=BackupExecutionRead)
def complete_backup(
    backup_id: uuid.UUID,
    payload: BackupCompleteRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BackupExecutionRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    repo = RecoveryRepository(db)
    backup = _backup_or_404(repo, backup_id, resolved_scope, resolved_org)
    policy = _policy_or_404(repo, backup.policy_id, resolved_scope, resolved_org)
    result = complete_backup_execution(db, policy, backup, payload)
    db.commit()
    return result


@router.post("/backups/{backup_id}/fail", response_model=BackupExecutionRead)
def fail_backup(
    backup_id: uuid.UUID,
    payload: RuntimeFailureRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BackupExecutionRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    backup = _backup_or_404(RecoveryRepository(db), backup_id, resolved_scope, resolved_org)
    result = fail_backup_execution(db, backup, payload)
    db.commit()
    return result


@router.post("/restores", response_model=RestoreExecutionRead)
def create_restore(
    payload: RestoreExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_restore_execution(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.get("/restores", response_model=list[RestoreExecutionRead])
def list_restores(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RestoreExecutionRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        RestoreExecutionRead.model_validate(item)
        for item in RecoveryRepository(db).list_restores(resolved_scope, resolved_org)
    ]


@router.get("/restores/{restore_id}", response_model=RestoreExecutionRead)
def read_restore(
    restore_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> RestoreExecutionRead:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    return RestoreExecutionRead.model_validate(
        _restore_or_404(RecoveryRepository(db), restore_id, resolved_scope, resolved_org)
    )


@router.post("/restores/{restore_id}/approve", response_model=RestoreExecutionRead)
def approve_restore(
    restore_id: uuid.UUID,
    payload: RestoreApproveRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreExecutionRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    restore = _restore_or_404(RecoveryRepository(db), restore_id, resolved_scope, resolved_org)
    result = approve_restore_execution(db, restore, payload)
    db.commit()
    return result


@router.post("/restores/{restore_id}/complete", response_model=RestoreExecutionRead)
def complete_restore(
    restore_id: uuid.UUID,
    payload: RestoreCompleteRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreExecutionRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    repo = RecoveryRepository(db)
    restore = _restore_or_404(repo, restore_id, resolved_scope, resolved_org)
    policy = _policy_or_404(repo, restore.policy_id, resolved_scope, resolved_org)
    result = complete_restore_execution(db, policy, restore, payload)
    db.commit()
    return result


@router.post("/restores/{restore_id}/fail", response_model=RestoreExecutionRead)
def fail_restore(
    restore_id: uuid.UUID,
    payload: RuntimeFailureRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreExecutionRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    restore = _restore_or_404(RecoveryRepository(db), restore_id, resolved_scope, resolved_org)
    result = fail_restore_execution(db, restore, payload)
    db.commit()
    return result


@router.post("/restores/{restore_id}/verifications", response_model=RestoreVerificationRead)
def create_verification(
    restore_id: uuid.UUID,
    payload: RestoreVerificationCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreVerificationRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    restore = _restore_or_404(RecoveryRepository(db), restore_id, resolved_scope, resolved_org)
    result = create_restore_verification(db, restore, payload)
    db.commit()
    return result


@router.get("/restores/{restore_id}/verifications", response_model=list[RestoreVerificationRead])
def list_verifications(
    restore_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> list[RestoreVerificationRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    repo = RecoveryRepository(db)
    _restore_or_404(repo, restore_id, resolved_scope, resolved_org)
    return [RestoreVerificationRead.model_validate(item) for item in repo.verifications_for_restore(restore_id)]


@router.get("/verifications/{verification_id}", response_model=RestoreVerificationRead)
def read_verification(
    verification_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreVerificationRead:
    _require(context, "read")
    repo = RecoveryRepository(db)
    verification = repo.get_verification(verification_id)
    if verification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="restore verification not found")
    resolved_scope, resolved_org = _scope(context)
    _restore_or_404(repo, verification.restore_execution_id, resolved_scope, resolved_org)
    return RestoreVerificationRead.model_validate(verification)


@router.post("/verifications/{verification_id}/complete", response_model=RestoreVerificationRead)
def complete_verification(
    verification_id: uuid.UUID,
    payload: RestoreVerificationCompleteRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreVerificationRead:
    _require(context, "administer")
    repo = RecoveryRepository(db)
    verification = repo.get_verification(verification_id)
    if verification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="restore verification not found")
    resolved_scope, resolved_org = _scope(context)
    restore = _restore_or_404(repo, verification.restore_execution_id, resolved_scope, resolved_org)
    policy = _policy_or_404(repo, restore.policy_id, resolved_scope, resolved_org)
    result = complete_restore_verification(db, policy, restore, verification, payload)
    db.commit()
    return result


@router.post("/verifications/{verification_id}/fail", response_model=RestoreVerificationRead)
def fail_verification(
    verification_id: uuid.UUID,
    payload: RuntimeFailureRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RestoreVerificationRead:
    _require(context, "administer")
    repo = RecoveryRepository(db)
    verification = repo.get_verification(verification_id)
    if verification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="restore verification not found")
    resolved_scope, resolved_org = _scope(context)
    _restore_or_404(repo, verification.restore_execution_id, resolved_scope, resolved_org)
    result = fail_restore_verification(db, verification, payload)
    db.commit()
    return result


@router.get("/readiness", response_model=RecoveryReadinessResponse)
def read_recovery_readiness(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RecoveryReadinessResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_recovery_readiness(db, scope=resolved_scope, organization_id=resolved_org)


@router.get("/runtime", response_model=RecoveryWorkspaceRuntimeResponse)
def read_recovery_workspace_runtime(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RecoveryWorkspaceRuntimeResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_recovery_workspace_runtime(db, scope=resolved_scope, organization_id=resolved_org)


@router.get("/evidence/latest", response_model=list[RecoveryEvidenceRead])
def read_latest_evidence(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RecoveryEvidenceRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        RecoveryEvidenceRead.model_validate(item)
        for item in RecoveryRepository(db).latest_evidence(resolved_scope, resolved_org)
    ]
