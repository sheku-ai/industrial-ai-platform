from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.scheduler_background_services import SchedulerBackgroundServicesRuntimeResponse
from app.services.scheduler_background_services_runtime import build_scheduler_background_services_runtime

router = APIRouter(prefix="/scheduler/background-services/center", tags=["scheduler-background-services"])


@router.get("/runtime", response_model=SchedulerBackgroundServicesRuntimeResponse)
def get_scheduler_background_services_runtime(db: Session = Depends(get_db)):
    return build_scheduler_background_services_runtime(db)
