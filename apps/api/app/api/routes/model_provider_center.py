from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.model_provider_center import ModelProviderCenterRuntimeResponse
from app.services.model_provider_center_runtime import build_model_provider_center_runtime

router = APIRouter(prefix="/models/providers/center", tags=["model-provider-center"])


@router.get("/runtime", response_model=ModelProviderCenterRuntimeResponse)
def get_model_provider_center_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if context.scope_type != "organization" or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization scope is required",
        )
    if not context.has_permission("ai.configuration", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI configuration read permission is required",
        )
    return build_model_provider_center_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=False,
    )
