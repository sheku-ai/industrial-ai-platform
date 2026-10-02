from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.document_workspace import DocumentWorkspaceRuntimeResponse
from app.services.document_workspace_runtime import build_document_workspace_runtime
from app.services.document_organization_associations import (
    DocumentOrganizationAssociationService,
)

router = APIRouter(prefix="/documents/workspace", tags=["document-workspace"])


@router.get("/runtime", response_model=DocumentWorkspaceRuntimeResponse)
def get_document_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if not context.has_permission("documents", "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="document read permission is required")
    runtime = build_document_workspace_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
    if (
        context.scope_type == "organization"
        and context.organization_id is not None
        and context.actor_reference
    ):
        return DocumentOrganizationAssociationService(
            db,
            organization_id=context.organization_id,
            actor_reference=context.actor_reference,
            actor_permissions=context.permissions,
            correlation_id=context.correlation_id,
        ).enrich_workspace(runtime)
    runtime["organization_associations"] = {
        "capabilities": {"read": False, "administer": False},
        "structure_options": [],
        "warnings": [{"code": "organization_scope_required"}],
        "limits": {"max_associations_per_document": 100},
        "association_semantics": "organizational_relation_only",
    }
    return runtime
