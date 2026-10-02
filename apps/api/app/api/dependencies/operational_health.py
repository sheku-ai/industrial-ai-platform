from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services.operational_health import OperationalHealthService, OperationalHealthThresholds


def get_operational_health_service(
    db: Session = Depends(get_db),
) -> OperationalHealthService:
    settings = get_settings()
    return OperationalHealthService(
        db,
        thresholds=OperationalHealthThresholds(
            pending_warning_seconds=settings.operational_health_pending_warning_seconds,
            stale_data_seconds=settings.operational_health_stale_data_seconds,
            failed_run_critical_count=settings.operational_health_failed_run_critical_count,
        ),
    )
