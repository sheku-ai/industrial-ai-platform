from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.enterprise_api_integration import EnterpriseApiIntegrationRuntimeResponse
from app.services.enterprise_api_integration_runtime import build_enterprise_api_integration_runtime

router = APIRouter(prefix="/enterprise/api-integration/center", tags=["enterprise-api-integration"])


@router.get("/runtime", response_model=EnterpriseApiIntegrationRuntimeResponse)
def get_enterprise_api_integration_runtime(
    request: Request,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return build_enterprise_api_integration_runtime(
        db,
        routes=request.app.routes,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
