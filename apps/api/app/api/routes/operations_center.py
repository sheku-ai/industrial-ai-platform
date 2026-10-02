from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.operations_center import OperationsCenterRuntimeResponse
from app.services.operations_center_runtime import build_operations_center_runtime

router = APIRouter(prefix="/platform/operations/center", tags=["operations-center"])


@router.get("/runtime", response_model=OperationsCenterRuntimeResponse)
def get_operations_center_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return {
        **build_operations_center_runtime(db),
        "authorization": {
            "platform.operations:read": context.has_permission("platform.operations", "read"),
            "platform.operations:administer": context.has_permission("platform.operations", "administer"),
        },
    }
