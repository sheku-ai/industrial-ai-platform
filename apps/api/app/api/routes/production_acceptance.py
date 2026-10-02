from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.release_operational_evidence import ReleaseOperationalEvidenceRepository
from app.schemas.production_acceptance import (
    ConfigurationPreflightResult,
    ProductionAcceptanceLatestResponse,
    ProductionAcceptanceRequest,
    ProductionAcceptanceRunResult,
    ProductionWorkspaceRuntimeResponse,
)
from app.schemas.production_readiness import ProductionReadinessRuntimeResponse
from app.schemas.release_operational_evidence import OperationalEvidenceRead, OperationalEvidenceRequest
from app.services.configuration_preflight import build_configuration_preflight
from app.services.production_acceptance_runtime import (
    build_production_workspace_runtime,
    get_latest_production_acceptance,
    get_production_acceptance_run,
    run_production_acceptance,
)
from app.services.production_readiness_runtime import build_production_readiness_runtime
from app.services.release_operational_evidence_runtime import refresh_configuration_preflight

router = APIRouter(prefix="/platform", tags=["production-acceptance"])


def _require(context: RuntimeRequestContext, resource: str, action: str) -> None:
    if not context.has_permission(resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{resource} {action} permission is required",
        )


def _scope_from_context(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="production acceptance run not found")
    return "organization", resolved_org


@router.post("/production-acceptance/runs", response_model=ProductionAcceptanceRunResult)
def create_production_acceptance_run(
    payload: ProductionAcceptanceRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProductionAcceptanceRunResult:
    _require(context, "platform.production_acceptance", "administer")
    scope, organization_id = _scope_from_context(context, payload.scope, payload.organization_id)
    request = payload.model_copy(update={"scope": scope, "organization_id": organization_id})
    if request.requested_by is None:
        request = request.model_copy(update={"requested_by": context.actor_reference})
    request = request.model_copy(update={"correlation_id": context.correlation_id})
    try:
        result = run_production_acceptance(db, request)
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.get("/production-acceptance/runs/{run_id}", response_model=ProductionAcceptanceRunResult)
def read_production_acceptance_run(
    run_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProductionAcceptanceRunResult:
    _require(context, "platform.production_acceptance", "read")
    result = get_production_acceptance_run(
        db,
        run_id,
        scope=context.scope_type,
        organization_id=context.organization_id,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="production acceptance run not found")
    return result


@router.get("/production-acceptance/latest", response_model=ProductionAcceptanceLatestResponse)
def read_latest_production_acceptance(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProductionAcceptanceLatestResponse:
    _require(context, "platform.production_acceptance", "read")
    resolved_scope, resolved_org = _scope_from_context(context, scope, organization_id)
    return get_latest_production_acceptance(db, scope=resolved_scope, organization_id=resolved_org)


@router.get("/production-acceptance/workspace", response_model=ProductionWorkspaceRuntimeResponse)
def read_platform_production_readiness(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProductionWorkspaceRuntimeResponse:
    _require(context, "platform.production_acceptance", "read")
    resolved_scope, resolved_org = _scope_from_context(context, scope, organization_id)
    return build_production_workspace_runtime(db, scope=resolved_scope, organization_id=resolved_org)


@router.get("/production-readiness/runtime", response_model=ProductionReadinessRuntimeResponse)
def read_platform_production_readiness_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ProductionReadinessRuntimeResponse:
    _require(context, "platform.production_acceptance", "read")
    if not context.is_scope("platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="platform authorization scope is required",
        )
    return ProductionReadinessRuntimeResponse.model_validate(
        build_production_readiness_runtime(db)
    )


@router.get("/configuration/preflight", response_model=ConfigurationPreflightResult)
def read_configuration_preflight(
    profile: str = Query(default="production"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ConfigurationPreflightResult:
    _require(context, "platform.configuration_preflight", "read")
    return build_configuration_preflight(profile, db=db, probe_dependencies=True)


@router.post("/configuration/preflight/refresh", response_model=OperationalEvidenceRead)
def create_configuration_preflight_evidence(
    payload: OperationalEvidenceRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _require(context, "platform.configuration_preflight", "administer")
    scope, organization_id = _scope_from_context(context, payload.scope, payload.organization_id)
    request = payload.model_copy(
        update={
            "scope": scope,
            "organization_id": organization_id,
            "correlation_id": context.correlation_id,
        }
    )
    try:
        result = refresh_configuration_preflight(db, request)
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.get("/configuration/preflight/evidence/latest", response_model=OperationalEvidenceRead)
def read_latest_configuration_preflight_evidence(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _require(context, "platform.configuration_preflight", "read")
    resolved_scope, resolved_org = _scope_from_context(context, scope, organization_id)
    row = ReleaseOperationalEvidenceRepository(db).latest(
        scope=resolved_scope,
        organization_id=resolved_org,
        evidence_type="configuration_preflight",
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="configuration_preflight_evidence_not_found")
    return OperationalEvidenceRead.model_validate(row)
