from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.assistant_workspace import (
    AssistantWorkspaceCapabilitiesResponse,
    AssistantWorkspaceRuntimeResponse,
)
from app.services.assistant_workspace_runtime import (
    build_assistant_workspace_runtime,
)

router = APIRouter(prefix="/assistants/workspace", tags=["assistant-workspace"])


@router.get("/capabilities", response_model=AssistantWorkspaceCapabilitiesResponse)
def get_assistant_workspace_capabilities(
    context: RuntimeRequestContext = Depends(get_runtime_context),
):
    can_read = context.has_permission("platform.assistants", "read")
    can_administer = context.has_permission("platform.assistants", "administer")
    organization_scoped = context.organization_id is not None
    available = can_read and organization_scoped
    return {
        "organization_id": str(context.organization_id) if context.organization_id else None,
        "assistant_read": can_read,
        "assistant_administer": can_administer,
        "workspace_available": available,
        "chat_available": available and can_administer,
        "conversations_available": available,
        "reason": (
            None
            if available
            else "assistant_permission_required"
            if organization_scoped
            else "organization_required"
        ),
    }


@router.get("/runtime", response_model=AssistantWorkspaceRuntimeResponse)
def get_assistant_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if not context.has_permission("platform.assistants", "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="assistant read permission is required")
    return build_assistant_workspace_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
