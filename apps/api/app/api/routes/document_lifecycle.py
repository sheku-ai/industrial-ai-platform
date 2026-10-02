from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.documents import DocumentLifecycleOrchestrateRequest, DocumentLifecycleOrchestrateResponse
from app.services.document_lifecycle_orchestrator import build_document_lifecycle_orchestration
from app.services.document_organization_associations import (
    DocumentOrganizationAssociationError,
)

router = APIRouter(prefix="/documents/lifecycle", tags=["document-lifecycle"])


@router.post("/orchestrate", response_model=DocumentLifecycleOrchestrateResponse, status_code=status.HTTP_201_CREATED)
def orchestrate_document_lifecycle(
    payload: DocumentLifecycleOrchestrateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    if context.organization_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization scope is required")
    if not context.has_permission("documents", "administer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="document administer permission is required")
    scoped_registration = payload.registration.model_copy(
        update={
            "organization_id": context.organization_id,
            "requested_by": context.actor_reference or payload.registration.requested_by,
        }
    )
    payload = payload.model_copy(
        update={
            "registration": scoped_registration,
            "requested_by": context.actor_reference or payload.requested_by,
        }
    )
    try:
        result = build_document_lifecycle_orchestration(
            db,
            payload=payload,
            actor_permissions=context.permissions,
        )
    except DocumentOrganizationAssociationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document lifecycle orchestration conflict"
        ) from exc
    if result.get("lifecycle_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=jsonable_encoder(result))
    return result
