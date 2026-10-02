from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies.operational_health import get_operational_health_service
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.schemas.operational_health import OperationalHealthResponse
from app.services.operational_health import OperationalHealthService

router = APIRouter(prefix="/control-plane/health", tags=["control-plane-health"])


@router.get("", response_model=OperationalHealthResponse)
def get_operational_health(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    service: OperationalHealthService = Depends(get_operational_health_service),
) -> OperationalHealthResponse:
    if not context.is_scope("organization") or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization authorization scope is required",
        )
    if not context.has_permission("control_plane.health", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operational health read permission is required",
        )

    try:
        return service.get_snapshot(context.organization_id)
    except SQLAlchemyError as exc:
        service.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operational health data is unavailable",
        ) from exc
