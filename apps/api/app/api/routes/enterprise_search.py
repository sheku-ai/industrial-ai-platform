from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.documents import EnterpriseSearchProductRequest
from app.services.enterprise_search_configuration import resolve_enterprise_search_configuration
from app.services.enterprise_search_persistence import persist_enterprise_search_result
from app.services.enterprise_search_runtime import build_enterprise_search
from app.services.knowledge_fts_runtime import build_knowledge_fts_health

router = APIRouter(prefix="/enterprise-search", tags=["enterprise-search"])


@router.post("/search")
def search_enterprise(
    payload: EnterpriseSearchProductRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization scope is required for enterprise search",
        )
    if not context.has_permission("knowledge_collections", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="knowledge collection read permission is required for enterprise search",
        )

    requested_limit = payload.limit if "limit" in payload.model_fields_set else None
    requested_top_k = payload.top_k if "top_k" in payload.model_fields_set else None
    try:
        search_configuration = resolve_enterprise_search_configuration(
            db,
            organization_id=context.organization_id,
            requested_limit=requested_limit,
            requested_top_k=requested_top_k,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    search_filters = {
        "organization_id": str(context.organization_id),
        "artifact_id": payload.artifact_id,
        "publication_id": payload.publication_id,
        "knowledge_document_id": payload.knowledge_document_id,
        "content_type": payload.content_type,
        "chunk_scope": payload.chunk_scope,
        "status": payload.status,
    }
    result = build_enterprise_search(
        db=db,
        query=payload.query,
        top_k=search_configuration.effective_top_k,
        offset=payload.offset,
        limit=search_configuration.effective_limit,
        include_facets=payload.include_facets,
        include_debug=payload.include_debug,
        search_config={"filters": search_filters},
        persist_snapshot=False,
    )
    result["search_configuration"] = search_configuration.as_dict()
    if result.get("search_status") != "blocked":
        result["runtime_persistence"] = persist_enterprise_search_result(
            db,
            organization_id=context.organization_id,
            query=payload.query,
            offset=payload.offset,
            limit=search_configuration.effective_limit,
            top_k=search_configuration.effective_top_k,
            filters=search_filters,
            include_facets=payload.include_facets,
            include_debug=payload.include_debug,
            result=result,
        )
    return result


@router.get("/health")
def get_enterprise_search_health(db: Session = Depends(get_db)):
    health = build_knowledge_fts_health(db)
    return {
        "enterprise_search_health_schema_version": "1",
        "enterprise_search_healthy": bool(health.get("fts_healthy")),
        "default_mode": "postgres_fts",
        "search_uses_postgresql": True,
        "search_uses_postgresql_fts": bool(health.get("search_uses_postgresql_fts")),
        "semantic_search_used": False,
        "embeddings_required": False,
        "ai_required": False,
        "knowledge_fts": health,
    }
