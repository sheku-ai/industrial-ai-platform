from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.portal_acceptance import PortalAcceptanceRepository
from app.schemas.portal_acceptance import (
    PortalAcceptanceEvidenceCreate,
    PortalAcceptanceEvidenceRead,
    PortalAcceptanceLatest,
    PortalAcceptanceReadiness,
)
from app.services.portal_acceptance_runtime import (
    build_portal_acceptance_readiness,
    latest_portal_acceptance,
    register_portal_evidence,
)

router = APIRouter(prefix="/platform/portal-acceptance", tags=["platform-portal-acceptance"])


def _authorize(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.portal_acceptance", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"portal acceptance {action} permission is required",
        )


def _scope(
    context: RuntimeRequestContext,
    requested_scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID | None]:
    scope = requested_scope or context.scope_type
    if scope == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="platform scope is required")
        return "platform", None
    resolved = organization_id or context.organization_id
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="portal evidence not found")
    return "organization", resolved


@router.post("/evidence", response_model=PortalAcceptanceEvidenceRead, status_code=status.HTTP_201_CREATED)
def create_evidence(
    payload: PortalAcceptanceEvidenceCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> PortalAcceptanceEvidenceRead:
    _authorize(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_portal_evidence(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "created_by": context.actor_reference,
                }
            ),
        )
    except ValueError as exc:
        raise runtime_http_error(exc) from exc
    db.commit()
    return result


@router.get("/evidence", response_model=list[PortalAcceptanceEvidenceRead])
def read_evidence(
    validation_run_code: str | None = Query(default=None),
    validation_type: str | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[PortalAcceptanceEvidenceRead]:
    _authorize(context, "read")
    scope, organization_id = _scope(context)
    return [
        PortalAcceptanceEvidenceRead.model_validate(item)
        for item in PortalAcceptanceRepository(db).list_evidence(
            scope,
            organization_id,
            validation_run_code=validation_run_code,
            validation_type=validation_type,
        )
    ]


@router.get("/readiness", response_model=PortalAcceptanceReadiness)
def read_readiness(
    validation_run_code: str | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> PortalAcceptanceReadiness:
    _authorize(context, "read")
    scope, organization_id = _scope(context)
    return build_portal_acceptance_readiness(
        db,
        scope=scope,
        organization_id=organization_id,
        validation_run_code=validation_run_code,
    )


@router.get("/latest", response_model=PortalAcceptanceLatest)
def read_latest(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> PortalAcceptanceLatest:
    _authorize(context, "read")
    scope, organization_id = _scope(context)
    return latest_portal_acceptance(db, scope=scope, organization_id=organization_id)
