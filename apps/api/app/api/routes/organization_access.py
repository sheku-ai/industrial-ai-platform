from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.identity.db import get_identity_db
from app.schemas.organization_access import (
    OrganizationAccessRuntimeResponse,
    OrganizationMembershipUpdate,
    OrganizationPolicyCreate,
    OrganizationPolicyUpdate,
    OrganizationRoleAssignmentCreate,
    OrganizationRoleCreate,
    OrganizationRoleDuplicate,
    OrganizationRoleUpdate,
    OrganizationUserCreate,
)
from app.services.organization_access_management import (
    OrganizationAccessError,
    OrganizationAccessManagementService,
)

router = APIRouter(prefix="/security/organization-access", tags=["organization-access"])


def _service(
    context: RuntimeRequestContext,
    db: Session,
    identity_db: Session,
) -> OrganizationAccessManagementService:
    if context.organization_id is None or context.scope_type != "organization":
        raise HTTPException(status_code=400, detail="organization_scope_required")
    if not context.actor_reference:
        raise HTTPException(status_code=401, detail="authenticated_actor_required")
    return OrganizationAccessManagementService(
        db,
        identity_db,
        organization_id=context.organization_id,
        actor_reference=context.actor_reference,
        actor_permissions=context.permissions,
        correlation_id=context.correlation_id,
    )


def _execute(service_call, db: Session, identity_db: Session) -> Any:
    try:
        return service_call()
    except OrganizationAccessError as exc:
        db.rollback()
        identity_db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except IntegrityError as exc:
        db.rollback()
        identity_db.rollback()
        raise HTTPException(status_code=409, detail="organization_access_conflict") from exc


@router.get("/runtime", response_model=OrganizationAccessRuntimeResponse)
def get_organization_access_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(service.runtime, db, identity_db)


@router.post("/users", status_code=201)
def create_organization_user(
    payload: OrganizationUserCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.create_user(payload), db, identity_db)


@router.patch("/memberships/{membership_id}")
def update_organization_membership(
    membership_id: uuid.UUID,
    payload: OrganizationMembershipUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.update_membership(membership_id, payload), db, identity_db)


@router.post("/memberships/{membership_id}/activate")
def activate_organization_membership(
    membership_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.set_membership_status(membership_id, "active"), db, identity_db)


@router.post("/memberships/{membership_id}/disable")
def disable_organization_membership(
    membership_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.set_membership_status(membership_id, "suspended"), db, identity_db)


@router.delete("/memberships/{membership_id}")
def remove_organization_membership(
    membership_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.set_membership_status(membership_id, "removed"), db, identity_db)


@router.post("/roles", status_code=201)
def create_organization_role(
    payload: OrganizationRoleCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.create_role(payload), db, identity_db)


@router.patch("/roles/{role_id}")
def update_organization_role(
    role_id: uuid.UUID,
    payload: OrganizationRoleUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.update_role(role_id, payload), db, identity_db)


@router.post("/roles/{role_id}/duplicate", status_code=201)
def duplicate_organization_role(
    role_id: uuid.UUID,
    payload: OrganizationRoleDuplicate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.duplicate_role(role_id, payload), db, identity_db)


@router.post("/roles/{role_id}/archive")
def archive_organization_role(
    role_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.archive_role(role_id), db, identity_db)


@router.post("/roles/{role_id}/status/{status}")
def set_organization_role_status(
    role_id: uuid.UUID,
    status: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.set_role_status(role_id, status), db, identity_db)


@router.delete("/roles/{role_id}")
def delete_organization_role(
    role_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.delete_role(role_id), db, identity_db)


@router.put("/roles/{role_id}/permissions/{permission_id}")
def attach_organization_role_permission(
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.add_role_permission(role_id, permission_id), db, identity_db)


@router.delete("/roles/{role_id}/permissions/{permission_id}")
def detach_organization_role_permission(
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.remove_role_permission(role_id, permission_id), db, identity_db)


@router.post("/assignments", status_code=201)
def create_organization_role_assignment(
    payload: OrganizationRoleAssignmentCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.create_assignment(payload), db, identity_db)


@router.delete("/assignments/{assignment_id}")
def remove_organization_role_assignment(
    assignment_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.remove_assignment(assignment_id), db, identity_db)


@router.post("/policies", status_code=201)
def create_organization_policy(
    payload: OrganizationPolicyCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.create_policy(payload), db, identity_db)


@router.patch("/policies/{policy_id}")
def update_organization_policy(
    policy_id: uuid.UUID,
    payload: OrganizationPolicyUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.update_policy(policy_id, payload), db, identity_db)


@router.post("/policies/{policy_id}/{status}")
def set_organization_policy_status(
    policy_id: uuid.UUID,
    status: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
):
    service = _service(context, db, identity_db)
    return _execute(lambda: service.set_policy_status(policy_id, status), db, identity_db)
