from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.ai_studio import AIStudioRuntimeResponse
from app.services.ai_studio_runtime import build_ai_studio_runtime

router = APIRouter(prefix="/ai/studio", tags=["ai-studio"])


@router.get("/runtime", response_model=AIStudioRuntimeResponse)
def get_ai_studio_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if not (
        context.has_permission("platform.assistants", "read")
        or context.has_permission("platform.assistants", "administer")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="assistant read permission is required",
        )
    return build_ai_studio_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
