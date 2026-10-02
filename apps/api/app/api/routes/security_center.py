from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.security_center import SecurityCenterRuntimeResponse
from app.services.security_center_runtime import build_security_center_runtime

router = APIRouter(prefix="/security/center", tags=["security-center"])


@router.get("/runtime", response_model=SecurityCenterRuntimeResponse)
def get_security_center_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return build_security_center_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
