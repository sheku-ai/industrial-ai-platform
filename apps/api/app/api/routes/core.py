import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_authenticated_principal
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.identity.contracts import AuthenticatedPrincipal
from app.models.core import Organization, OrganizationNode, OrganizationRelationship
from app.repositories.base import Repository
from app.schemas.core import (
    OrganizationCreate,
    OrganizationDeletionExecutionRead,
    OrganizationDeletionRequest,
    OrganizationNodeCreate,
    OrganizationNodeRead,
    OrganizationNodeUpdate,
    OrganizationRead,
    OrganizationRelationshipCreate,
    OrganizationRelationshipRead,
    OrganizationRelationshipUpdate,
    OrganizationUpdate,
)
from app.services.base import CRUDService
from app.services.organization_deletion import (
    delete_organization_governed,
    get_organization_deletion_status,
    preview_organization_deletion,
)

router = APIRouter(prefix="/core", tags=["core"])

organization_service = CRUDService(Repository(Organization))
node_service = CRUDService(Repository(OrganizationNode))
relationship_service = CRUDService(Repository(OrganizationRelationship))


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")


def _structure_transaction_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="organization_structure_transaction_required",
    )


def _require_configuration(context: RuntimeRequestContext, action: str) -> uuid.UUID:
    if context.organization_id is None or not context.has_permission("reference_tenant", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="organization configuration permission required"
        )
    return context.organization_id


def _require_organization_lifecycle(
    context: RuntimeRequestContext,
    organization_id: uuid.UUID,
    action: str,
) -> str:
    if not context.actor_reference:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authenticated actor required")
    platform_authorized = (
        context.scope_type == "platform" and context.has_permission("platform.organization_lifecycle", action)
    )
    organization_authorized = (
        context.scope_type == "organization"
        and context.organization_id == organization_id
        and context.has_permission("reference_tenant", "administer" if action == "administer" else "read")
    )
    if not platform_authorized and not organization_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization lifecycle permission required",
        )
    return context.actor_reference


def _deletion_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail == "organization_not_found":
        return _not_found("organization")
    if detail == "organization_deletion_idempotency_conflict":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if detail in {"organization_deletion_preview_required", "organization_deletion_not_ready"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _node_to_dict(item: OrganizationNode) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "parent_node_id": item.parent_node_id,
        "node_type": item.node_type,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "metadata": item.metadata_json,
        "position": item.position,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "created_by": item.created_by,
        "updated_by": item.updated_by,
    }


def _relationship_to_dict(item: OrganizationRelationship) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "source_node_id": item.source_node_id,
        "target_node_id": item.target_node_id,
        "relationship_type": item.relationship_type,
        "metadata": item.metadata_json,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "created_by": item.created_by,
        "updated_by": item.updated_by,
    }


def _with_metadata_json(data: dict[str, Any]) -> dict[str, Any]:
    if "metadata" in data:
        data["metadata_json"] = data.pop("metadata")
    return data


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    operational_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    authorized_organization_ids = principal.organization_ids
    if not authorized_organization_ids:
        return []
    organizations = list(
        db.scalars(
            select(Organization)
            .where(Organization.id.in_(authorized_organization_ids))
            .order_by(Organization.name.asc(), Organization.id.asc())
        ).all()
    )
    if not operational_only:
        return organizations[skip : skip + limit]
    operational = [
        item
        for item in organizations
        if not (
            (item.config or {}).get("smoke") is True
            or (item.config or {}).get("validation_generated") is True
            or (item.config or {}).get("scenario") == "local_product_acceptance"
            or (item.config or {}).get("execution_key")
        )
    ]
    return operational[skip : skip + limit]


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    return organization_service.create(db, payload.model_dump())


@router.get("/organizations/{organization_id}", response_model=OrganizationRead)
def get_organization(organization_id: uuid.UUID, db: Session = Depends(get_db)):
    item = organization_service.get(db, organization_id)
    if item is None:
        raise _not_found("organization")
    return item


@router.patch("/organizations/{organization_id}", response_model=OrganizationRead)
def update_organization(organization_id: uuid.UUID, payload: OrganizationUpdate, db: Session = Depends(get_db)):
    item = organization_service.get(db, organization_id)
    if item is None:
        raise _not_found("organization")
    return organization_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.post(
    "/organizations/{organization_id}/deletion-preview",
    response_model=OrganizationDeletionExecutionRead,
)
def preview_organization_deletion_route(
    organization_id: uuid.UUID,
    payload: OrganizationDeletionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    requested_by = _require_organization_lifecycle(context, organization_id, "administer")
    item = organization_service.get(db, organization_id)
    if item is None:
        raise _not_found("organization")
    try:
        result = preview_organization_deletion(
            db,
            item,
            payload,
            requested_by=requested_by,
            correlation_id=context.correlation_id,
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise _deletion_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/delete",
    response_model=OrganizationDeletionExecutionRead,
)
def delete_organization_route(
    organization_id: uuid.UUID,
    payload: OrganizationDeletionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    requested_by = _require_organization_lifecycle(context, organization_id, "administer")
    try:
        return delete_organization_governed(
            db,
            organization_id,
            payload,
            requested_by=requested_by,
            correlation_id=context.correlation_id,
        )
    except ValueError as exc:
        db.rollback()
        raise _deletion_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/deletion-status",
    response_model=OrganizationDeletionExecutionRead,
)
def get_organization_deletion_status_route(
    organization_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require_organization_lifecycle(context, organization_id, "read")
    result = get_organization_deletion_status(db, organization_id)
    if result is None:
        raise _not_found("organization deletion execution")
    return result


@router.delete("/organizations/{organization_id}")
def delete_organization_legacy(
    organization_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
):
    _require_organization_lifecycle(context, organization_id, "administer")
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="governed organization deletion preview required",
    )


@router.get("/organization-nodes", response_model=list[OrganizationNodeRead])
def list_organization_nodes(
    skip: int = 0,
    limit: int = 100,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_configuration(context, "read")
    statement = (
        select(OrganizationNode).where(OrganizationNode.organization_id == organization_id).offset(skip).limit(limit)
    )
    return [_node_to_dict(item) for item in db.scalars(statement).all()]


@router.post("/organization-nodes", response_model=OrganizationNodeRead, status_code=status.HTTP_201_CREATED)
def create_organization_node(
    payload: OrganizationNodeCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del payload, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()


@router.get("/organization-nodes/{node_id}", response_model=OrganizationNodeRead)
def get_organization_node(
    node_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_configuration(context, "read")
    item = node_service.get(db, node_id)
    if item is None or item.organization_id != organization_id:
        raise _not_found("organization node")
    return _node_to_dict(item)


@router.patch("/organization-nodes/{node_id}", response_model=OrganizationNodeRead)
def update_organization_node(
    node_id: uuid.UUID,
    payload: OrganizationNodeUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del node_id, payload, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()


@router.delete("/organization-nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization_node(
    node_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del node_id, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()


@router.get("/organization-relationships", response_model=list[OrganizationRelationshipRead])
def list_organization_relationships(
    skip: int = 0,
    limit: int = 100,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_configuration(context, "read")
    statement = (
        select(OrganizationRelationship)
        .where(OrganizationRelationship.organization_id == organization_id)
        .offset(skip)
        .limit(limit)
    )
    return [_relationship_to_dict(item) for item in db.scalars(statement).all()]


@router.post(
    "/organization-relationships", response_model=OrganizationRelationshipRead, status_code=status.HTTP_201_CREATED
)
def create_organization_relationship(
    payload: OrganizationRelationshipCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del payload, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()


@router.get("/organization-relationships/{relationship_id}", response_model=OrganizationRelationshipRead)
def get_organization_relationship(
    relationship_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_configuration(context, "read")
    item = relationship_service.get(db, relationship_id)
    if item is None or item.organization_id != organization_id:
        raise _not_found("organization relationship")
    return _relationship_to_dict(item)


@router.patch("/organization-relationships/{relationship_id}", response_model=OrganizationRelationshipRead)
def update_organization_relationship(
    relationship_id: uuid.UUID,
    payload: OrganizationRelationshipUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del relationship_id, payload, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()


@router.delete("/organization-relationships/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization_relationship(
    relationship_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    del relationship_id, db
    _require_configuration(context, "administer")
    raise _structure_transaction_required()
