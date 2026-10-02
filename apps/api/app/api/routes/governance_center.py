from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.governance_center import GovernanceCenterRuntimeResponse
from app.services.governance_center_runtime import build_governance_center_runtime

router = APIRouter(prefix="/platform/governance/center", tags=["governance-center"])


@router.get("/runtime", response_model=GovernanceCenterRuntimeResponse)
def get_governance_center_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if context.scope_type == "organization" and (
        context.organization_id is None or not context.permissions
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="authorized organization access is required",
        )
    return build_governance_center_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
