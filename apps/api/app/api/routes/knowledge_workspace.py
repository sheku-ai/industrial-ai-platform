from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.knowledge_workspace import KnowledgeWorkspaceRuntimeResponse
from app.services.knowledge_workspace_runtime import build_knowledge_workspace_runtime

router = APIRouter(prefix="/knowledge/workspace", tags=["knowledge-workspace"])


@router.get("/runtime", response_model=KnowledgeWorkspaceRuntimeResponse)
def get_knowledge_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return build_knowledge_workspace_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
