from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.reporting_analytics import ReportingAnalyticsRuntimeResponse
from app.services.reporting_analytics_runtime import build_reporting_analytics_runtime

router = APIRouter(prefix="/reporting/analytics/center", tags=["reporting-analytics"])


@router.get("/runtime", response_model=ReportingAnalyticsRuntimeResponse)
def get_reporting_analytics_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return build_reporting_analytics_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
