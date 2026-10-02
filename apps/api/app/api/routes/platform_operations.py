from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.platform_operations import PlatformOperationsRuntimeResponse
from app.services.platform_operations_runtime import build_platform_operations_runtime

router = APIRouter(prefix="/platform/operations", tags=["platform-operations"])


@router.get("/runtime", response_model=PlatformOperationsRuntimeResponse)
def get_platform_operations_runtime(db: Session = Depends(get_db)):
    return build_platform_operations_runtime(db)
