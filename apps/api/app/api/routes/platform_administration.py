from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.platform_administration import PlatformAdministrationRuntimeResponse
from app.services.platform_administration_runtime import build_platform_administration_runtime

router = APIRouter(prefix="/platform/administration", tags=["platform-administration"])


@router.get("/runtime", response_model=PlatformAdministrationRuntimeResponse)
def get_platform_administration_runtime(
    include_validation: bool = Query(default=False),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    platform_scope = context.scope_type == "platform"
    if platform_scope and not context.has_permission("platform.security", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="platform administration permission is required",
        )
    if not platform_scope and context.organization_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization scope is required")
    if not platform_scope and not (
        context.has_permission("reference_tenant", "read")
        or context.has_permission("reference_tenant", "administer")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization administration permission is required",
        )
    if include_validation and not platform_scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="validation data requires explicitly authorized platform scope",
        )
    return build_platform_administration_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=platform_scope,
        include_validation=include_validation,
    )
