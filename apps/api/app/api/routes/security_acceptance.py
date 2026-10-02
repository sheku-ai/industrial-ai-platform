from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.security_acceptance import SecurityAcceptanceRepository
from app.schemas.security_acceptance import (
    SecurityConfigurationResponse,
    SecurityEvaluationRequest,
    SecurityEvidenceRead,
    SecurityFindingRead,
    SecurityPolicyCreate,
    SecurityPolicyRead,
    SecurityPolicyUpdate,
    SecurityReadinessResponse,
    SecurityWorkspaceRuntimeResponse,
)
from app.services.security_acceptance_authoritative_runtime import (
    activate_security_policy,
    build_security_configuration,
    build_security_readiness,
    build_security_workspace_runtime,
    create_security_policy,
    update_security_policy,
)

router = APIRouter(prefix="/platform/security", tags=["platform-security"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.security", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"platform.security {action} permission is required",
        )


def _scope(
    context: RuntimeRequestContext,
    requested_scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID | None]:
    scope = requested_scope or context.scope_type
    if scope == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="platform authorization scope is required",
            )
        return "platform", None
    resolved_org = organization_id or context.organization_id
    if resolved_org is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="security resource not found")
    return "organization", resolved_org


@router.get("/readiness", response_model=SecurityReadinessResponse)
def get_security_readiness(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityReadinessResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_security_readiness(db, resolved_scope, resolved_org)


@router.get("/findings", response_model=list[SecurityFindingRead])
def list_security_findings(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[SecurityFindingRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        SecurityFindingRead.model_validate(item)
        for item in SecurityAcceptanceRepository(db).list_findings(resolved_scope, resolved_org)
    ]


@router.get("/evidence/latest", response_model=list[SecurityEvidenceRead])
def latest_security_evidence(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[SecurityEvidenceRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        SecurityEvidenceRead.model_validate(item)
        for item in SecurityAcceptanceRepository(db).list_evidence(resolved_scope, resolved_org)[:50]
    ]


@router.get("/policies", response_model=list[SecurityPolicyRead])
def list_security_policies(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[SecurityPolicyRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        SecurityPolicyRead.model_validate(item)
        for item in SecurityAcceptanceRepository(db).list_policies(resolved_scope, resolved_org)
    ]


@router.post("/policies", response_model=SecurityPolicyRead)
def create_policy(
    payload: SecurityPolicyCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityPolicyRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context, payload.scope, payload.organization_id)
    try:
        result = create_security_policy(
            db, payload.model_copy(update={"scope": resolved_scope, "organization_id": resolved_org})
        )
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.patch("/policies/{policy_id}", response_model=SecurityPolicyRead)
def patch_policy(
    policy_id: uuid.UUID,
    payload: SecurityPolicyUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityPolicyRead:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context)
    policy = SecurityAcceptanceRepository(db).get_policy(policy_id, resolved_scope, resolved_org)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="security policy not found")
    result = update_security_policy(db, policy, payload)
    if payload.status == "active":
        result = activate_security_policy(db, policy)
    db.commit()
    return result


@router.post("/evaluate", response_model=SecurityReadinessResponse)
def evaluate_security(
    payload: SecurityEvaluationRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityReadinessResponse:
    _require(context, "administer")
    resolved_scope, resolved_org = _scope(context, payload.scope, payload.organization_id)
    result = build_security_readiness(db, resolved_scope, resolved_org, refresh=True)
    db.commit()
    return result


@router.get("/configuration", response_model=SecurityConfigurationResponse)
def get_security_configuration(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityConfigurationResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    result = build_security_configuration(db, resolved_scope, resolved_org)
    db.commit()
    return result


@router.get("/workspace/runtime", response_model=SecurityWorkspaceRuntimeResponse)
def get_security_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> SecurityWorkspaceRuntimeResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context)
    result = build_security_workspace_runtime(db, resolved_scope, resolved_org)
    db.commit()
    return result
