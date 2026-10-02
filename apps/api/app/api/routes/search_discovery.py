from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.search_discovery import SearchDiscoveryRuntimeResponse
from app.services.search_discovery_runtime import build_search_discovery_runtime

router = APIRouter(prefix="/search/discovery", tags=["search-discovery"])


@router.get("/runtime", response_model=SearchDiscoveryRuntimeResponse)
def get_search_discovery_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if context.organization_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization scope is required")
    if not context.has_permission("knowledge_collections", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="knowledge collection read permission is required",
        )
    return build_search_discovery_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=False,
    )
