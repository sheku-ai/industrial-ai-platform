from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.organization_structure import (
    OrganizationStructureConvergenceApplyRequest,
    OrganizationStructureConvergenceApplyResponse,
    OrganizationStructureConvergencePreviewRequest,
    OrganizationStructureConvergencePreviewResponse,
    OrganizationStructureRuntimeResponse,
    OrganizationStructureSaveRequest,
)
from app.services.organization_structure import (
    OrganizationStructureError,
    OrganizationStructureService,
)

router = APIRouter(
    prefix="/core/organization-structure",
    tags=["organization-structure"],
)


def _service(
    context: RuntimeRequestContext,
    db: Session,
) -> OrganizationStructureService:
    if not context.actor_reference:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
        )
    if context.scope_type != "organization" or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization_scope_required",
        )
    return OrganizationStructureService(
        db,
        organization_id=context.organization_id,
        actor_reference=context.actor_reference,
        actor_permissions=context.permissions,
        correlation_id=context.correlation_id,
    )


def _error(exc: OrganizationStructureError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code},
    )


@router.get("/runtime", response_model=OrganizationStructureRuntimeResponse)
def get_organization_structure_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        return _service(context, db).runtime()
    except OrganizationStructureError as exc:
        raise _error(exc) from exc


@router.post(
    "/convergence/preview",
    response_model=OrganizationStructureConvergencePreviewResponse,
)
def preview_organization_structure_convergence(
    payload: OrganizationStructureConvergencePreviewRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        return _service(context, db).convergence_preview(payload)
    except OrganizationStructureError as exc:
        raise _error(exc) from exc


@router.post(
    "/convergence/apply",
    response_model=OrganizationStructureConvergenceApplyResponse,
)
def apply_organization_structure_convergence(
    payload: OrganizationStructureConvergenceApplyRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        result = _service(context, db).apply_convergence(payload)
        db.commit()
        return result
    except OrganizationStructureError as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "organization_structure_persistence_conflict"},
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.put("/runtime", response_model=OrganizationStructureRuntimeResponse)
def save_organization_structure_runtime(
    payload: OrganizationStructureSaveRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        result = _service(context, db).save(payload)
        db.commit()
        return result
    except OrganizationStructureError as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "organization_structure_persistence_conflict"},
        ) from exc
    except Exception:
        db.rollback()
        raise
