from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import (
    RuntimeRequestContext,
    get_runtime_context,
)
from app.db.session import get_db
from app.schemas.document_organization_associations import (
    DocumentOrganizationAssociationRuntimeResponse,
    DocumentOrganizationAssociationSaveRequest,
)
from app.services.document_organization_associations import (
    DocumentOrganizationAssociationError,
    DocumentOrganizationAssociationService,
)

router = APIRouter(
    prefix="/documents",
    tags=["document-organization-associations"],
)


def _service(
    context: RuntimeRequestContext,
    db: Session,
) -> DocumentOrganizationAssociationService:
    if not context.actor_reference:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
        )
    if context.scope_type != "organization" or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization_scope_required",
        )
    return DocumentOrganizationAssociationService(
        db,
        organization_id=context.organization_id,
        actor_reference=context.actor_reference,
        actor_permissions=context.permissions,
        correlation_id=context.correlation_id,
    )


def _error(exc: DocumentOrganizationAssociationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code},
    )


@router.get(
    "/{document_id}/organization-associations",
    response_model=DocumentOrganizationAssociationRuntimeResponse,
)
def get_document_organization_associations(
    document_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        return _service(context, db).runtime(document_id)
    except DocumentOrganizationAssociationError as exc:
        raise _error(exc) from exc


@router.put(
    "/{document_id}/organization-associations",
    response_model=DocumentOrganizationAssociationRuntimeResponse,
)
def save_document_organization_associations(
    document_id: uuid.UUID,
    payload: DocumentOrganizationAssociationSaveRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    try:
        result = _service(context, db).save(document_id, payload)
        db.commit()
        return result
    except DocumentOrganizationAssociationError as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "document_organization_association_persistence_conflict"
            },
        ) from exc
    except Exception:
        db.rollback()
        raise

