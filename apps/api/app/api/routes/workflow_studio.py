from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.workflow_studio import WorkflowStudioRuntimeResponse
from app.services.workflow_studio_runtime import build_workflow_studio_runtime

router = APIRouter(prefix="/workflows/studio", tags=["workflow-studio"])


@router.get("/runtime", response_model=WorkflowStudioRuntimeResponse)
def get_workflow_studio_runtime(db: Session = Depends(get_db)):
    return build_workflow_studio_runtime(db)
