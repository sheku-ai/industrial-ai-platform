from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.crud import register_crud_routes
from app.models.security import Permission, Policy, Role, RoleAssignment, RolePermission
from app.repositories.base import Repository
from app.schemas.security import (
    PermissionCreate,
    PermissionRead,
    PermissionUpdate,
    PolicyCreate,
    PolicyRead,
    PolicyUpdate,
    RoleAssignmentCreate,
    RoleAssignmentRead,
    RoleAssignmentUpdate,
    RoleCreate,
    RolePermissionCreate,
    RolePermissionRead,
    RolePermissionUpdate,
    RoleRead,
    RoleUpdate,
)
from app.services.base import CRUDService

router = APIRouter(prefix="/security", tags=["security"])


def _governed_global_role_required() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="global_role_governed_endpoint_required",
    )


def _guard_role_mutation(
    operation: str,
    item: Role | None,
    data: dict[str, Any] | None,
    db: Session,
) -> None:
    del operation, db
    if item is not None and item.organization_id is None:
        _governed_global_role_required()
    if item is None and (data or {}).get("organization_id") is None:
        _governed_global_role_required()


def _guard_role_permission_mutation(
    operation: str,
    item: RolePermission | None,
    data: dict[str, Any] | None,
    db: Session,
) -> None:
    del operation
    role_ids = {
        role_id
        for role_id in (
            item.role_id if item is not None else None,
            (data or {}).get("role_id"),
        )
        if role_id is not None
    }
    for role_id in role_ids:
        role = db.get(Role, role_id)
        if role is not None and role.organization_id is None:
            _governed_global_role_required()


def _guard_permission_mutation(
    operation: str,
    item: Permission | None,
    data: dict[str, Any] | None,
    db: Session,
) -> None:
    del data
    if operation == "create" or item is None:
        return
    global_role_link = db.scalar(
        select(RolePermission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(
            RolePermission.permission_id == item.id,
            Role.organization_id.is_(None),
        )
        .limit(1)
    )
    if global_role_link is not None:
        _governed_global_role_required()


register_crud_routes(
    router,
    "/roles",
    "role",
    CRUDService(Repository(Role)),
    RoleCreate,
    RoleUpdate,
    RoleRead,
    mutation_guard=_guard_role_mutation,
)
register_crud_routes(
    router,
    "/permissions",
    "permission",
    CRUDService(Repository(Permission)),
    PermissionCreate,
    PermissionUpdate,
    PermissionRead,
    mutation_guard=_guard_permission_mutation,
)
register_crud_routes(
    router,
    "/role-permissions",
    "role permission",
    CRUDService(Repository(RolePermission)),
    RolePermissionCreate,
    RolePermissionUpdate,
    RolePermissionRead,
    mutation_guard=_guard_role_permission_mutation,
)
register_crud_routes(
    router, "/policies", "policy", CRUDService(Repository(Policy)), PolicyCreate, PolicyUpdate, PolicyRead
)
register_crud_routes(
    router,
    "/role-assignments",
    "role assignment",
    CRUDService(Repository(RoleAssignment)),
    RoleAssignmentCreate,
    RoleAssignmentUpdate,
    RoleAssignmentRead,
)
