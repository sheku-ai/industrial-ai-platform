import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.db import get_identity_db
from app.models.security import Permission
from app.schemas.security_management import (
    GlobalMembershipMutation,
    GlobalPasswordReset,
    GlobalRoleRead,
    GlobalRoleReconcileRequest,
    GlobalRoleStatusRead,
    GlobalUserCreate,
    GlobalUserMutationResult,
    GlobalUserRuntime,
    GlobalUserUpdate,
    ManagedPermissionCreate,
    ManagedPermissionRead,
    ManagedPolicyCreate,
    ManagedPolicyRead,
    ManagedPolicyUpdate,
    ManagedRoleAssignmentCreate,
    ManagedRoleAssignmentRead,
    ManagedRoleAssignmentUpdate,
    ManagedRoleCreate,
    ManagedRolePermissionRead,
    ManagedRoleRead,
    ManagedRoleUpdate,
    PrincipalPermissionResolutionRequest,
    PrincipalPermissionResolutionResponse,
    SecurityManagementReadiness,
)
from app.services.global_user_management import (
    GlobalUserManagementError,
    GlobalUserManagementService,
)
from app.services.security_management import (
    GlobalRoleManagementError,
    GlobalRoleManagementService,
    attach_role_permission,
    build_security_management_readiness,
    create_permission,
    create_policy,
    create_role,
    create_role_assignment,
    get_assignment,
    get_policy,
    get_role,
    list_permissions,
    list_policies,
    list_role_assignments,
    list_role_permissions,
    list_roles,
    remove_role_permission,
    resolve_principal_permissions,
    update_policy,
    update_role,
    update_role_assignment,
)

router = APIRouter(prefix="/security/management", tags=["security-management"])


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")


def _conflict(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "security_management_conflict", "details": str(getattr(exc, "orig", exc))},
    )


def _global_role_service(context: RuntimeRequestContext, db: Session) -> GlobalRoleManagementService:
    if context.scope_type != "platform" or context.organization_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="platform_scope_required")
    if not context.has_permission("platform.security", "administer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission_required")
    if not context.actor_reference:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authenticated_actor_required")
    return GlobalRoleManagementService(
        db,
        actor_reference=context.actor_reference,
        correlation_id=context.correlation_id,
    )


def _execute_global(operation, db: Session):
    try:
        return operation()
    except GlobalRoleManagementError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def _global_user_service(
    context: RuntimeRequestContext,
    identity_db: Session,
    db: Session,
    settings: Settings,
) -> GlobalUserManagementService:
    if context.scope_type != "platform" or context.organization_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="platform_scope_required")
    if not context.has_permission("platform.security", "administer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission_required")
    if not context.actor_reference:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authenticated_actor_required")
    return GlobalUserManagementService(
        identity_db,
        db,
        settings,
        actor_reference=context.actor_reference,
        correlation_id=context.correlation_id,
    )


def _execute_global_user(operation, identity_db: Session, db: Session):
    try:
        return operation()
    except GlobalUserManagementError as exc:
        identity_db.rollback()
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/global-users/runtime", response_model=GlobalUserRuntime)
def global_user_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(service.runtime, identity_db, db)


@router.post("/global-users", response_model=GlobalUserMutationResult, status_code=status.HTTP_201_CREATED)
def create_global_user(
    payload: GlobalUserCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.create(**payload.model_dump()), identity_db, db)


@router.patch("/global-users/{user_id}", response_model=GlobalUserMutationResult)
def update_global_user(
    user_id: uuid.UUID,
    payload: GlobalUserUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.update(user_id, payload.model_dump(exclude_unset=True)), identity_db, db)


@router.post("/global-users/{user_id}/reset-password", response_model=GlobalUserMutationResult)
def reset_global_user_password(
    user_id: uuid.UUID,
    payload: GlobalPasswordReset,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.reset_password(user_id, payload.temporary_password), identity_db, db)


@router.post("/global-users/{user_id}/revoke-sessions", response_model=GlobalUserMutationResult)
def revoke_global_user_sessions(
    user_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.revoke_sessions(user_id), identity_db, db)


@router.post("/global-users/{user_id}/{action}", response_model=GlobalUserMutationResult)
def change_global_user_status(
    user_id: uuid.UUID,
    action: Literal["activate", "deactivate"],
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.set_status(user_id, action == "activate"), identity_db, db)


@router.put("/global-users/{user_id}/global-roles/{role_id}", response_model=GlobalUserMutationResult)
@router.delete("/global-users/{user_id}/global-roles/{role_id}", response_model=GlobalUserMutationResult)
def change_global_user_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    request: Request,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.set_role(user_id, role_id, None, request.method == "PUT"), identity_db, db)


@router.put("/global-users/{user_id}/memberships/{organization_id}", response_model=GlobalUserMutationResult)
def assign_global_user_membership(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    payload: GlobalMembershipMutation,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.set_membership(user_id, organization_id, payload.role_id, True), identity_db, db)


@router.delete("/global-users/{user_id}/memberships/{organization_id}", response_model=GlobalUserMutationResult)
def remove_global_user_membership(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.set_membership(user_id, organization_id, None, False), identity_db, db)


@router.put("/global-users/{user_id}/organizations/{organization_id}/roles/{role_id}", response_model=GlobalUserMutationResult)
@router.delete("/global-users/{user_id}/organizations/{organization_id}/roles/{role_id}", response_model=GlobalUserMutationResult)
def change_global_user_organization_role(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    request: Request,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.set_role(user_id, role_id, organization_id, request.method == "PUT"), identity_db, db)


@router.delete("/global-users/{user_id}", response_model=GlobalUserMutationResult)
def delete_global_user(
    user_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    identity_db: Session = Depends(get_identity_db),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    service = _global_user_service(context, identity_db, db, settings)
    return _execute_global_user(lambda: service.delete(user_id), identity_db, db)


def _reject_global_role_mutation(role) -> None:
    if role.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="global_role_governed_endpoint_required",
        )


@router.get("/global-roles", response_model=list[GlobalRoleRead])
def read_global_roles(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    service = _global_role_service(context, db)
    return _execute_global(service.list_roles, db)


@router.post("/global-roles/reconcile", response_model=GlobalRoleRead)
def reconcile_global_role(
    payload: GlobalRoleReconcileRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    service = _global_role_service(context, db)
    return _execute_global(lambda: service.reconcile(**payload.model_dump()), db)


@router.post("/global-roles/{code}/deactivate", response_model=GlobalRoleStatusRead)
def deactivate_global_role(
    code: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    service = _global_role_service(context, db)
    return _execute_global(lambda: service.deactivate(code), db)


@router.post("/global-roles/{code}/activate", response_model=GlobalRoleStatusRead)
def activate_global_role(
    code: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    service = _global_role_service(context, db)
    return _execute_global(lambda: service.activate(code), db)


@router.get("/readiness", response_model=SecurityManagementReadiness)
def readiness(db: Session = Depends(get_db)):
    return build_security_management_readiness(db)


@router.get("/roles", response_model=list[ManagedRoleRead])
def read_roles(
    organization_id: uuid.UUID | None = Query(default=None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_roles(db, organization_id=organization_id, skip=skip, limit=limit)


@router.post("/roles", response_model=ManagedRoleRead, status_code=status.HTTP_201_CREATED)
def add_role(payload: ManagedRoleCreate, db: Session = Depends(get_db)):
    if payload.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="global_role_governed_endpoint_required",
        )
    try:
        return create_role(db, payload.model_dump())
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.get("/roles/{role_id}", response_model=ManagedRoleRead)
def read_role(role_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    return role


@router.patch("/roles/{role_id}", response_model=ManagedRoleRead)
def edit_role(role_id: uuid.UUID, payload: ManagedRoleUpdate, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    _reject_global_role_mutation(role)
    try:
        return update_role(db, role, payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.post("/roles/{role_id}/activate", response_model=ManagedRoleRead)
def activate_role(role_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    _reject_global_role_mutation(role)
    return update_role(db, role, {"status": "active"})


@router.post("/roles/{role_id}/deactivate", response_model=ManagedRoleRead)
def deactivate_role(role_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    _reject_global_role_mutation(role)
    return update_role(db, role, {"status": "inactive"})


@router.get("/roles/{role_id}/permissions", response_model=list[ManagedRolePermissionRead])
def read_role_permissions(role_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    return list_role_permissions(db, role)


@router.post("/roles/{role_id}/permissions/{permission_id}", response_model=ManagedRolePermissionRead)
def attach_permission_to_role(role_id: uuid.UUID, permission_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    _reject_global_role_mutation(role)
    permission = db.get(Permission, permission_id)
    if permission is None:
        raise _not_found("permission")
    try:
        return attach_role_permission(db, role, permission)
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach_permission_from_role(role_id: uuid.UUID, permission_id: uuid.UUID, db: Session = Depends(get_db)):
    role = get_role(db, role_id)
    if role is None:
        raise _not_found("role")
    _reject_global_role_mutation(role)
    permission = db.get(Permission, permission_id)
    if permission is None:
        raise _not_found("permission")
    remove_role_permission(db, role, permission)


@router.get("/permissions", response_model=list[ManagedPermissionRead])
def read_permissions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return list_permissions(db, skip=skip, limit=limit)


@router.post("/permissions", response_model=ManagedPermissionRead, status_code=status.HTTP_201_CREATED)
def add_permission(payload: ManagedPermissionCreate, db: Session = Depends(get_db)):
    try:
        return create_permission(db, payload.model_dump())
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.get("/policies", response_model=list[ManagedPolicyRead])
def read_policies(
    organization_id: uuid.UUID | None = Query(default=None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_policies(db, organization_id=organization_id, skip=skip, limit=limit)


@router.post("/policies", response_model=ManagedPolicyRead, status_code=status.HTTP_201_CREATED)
def add_policy(payload: ManagedPolicyCreate, db: Session = Depends(get_db)):
    try:
        return create_policy(db, payload.model_dump())
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.patch("/policies/{policy_id}", response_model=ManagedPolicyRead)
def edit_policy(policy_id: uuid.UUID, payload: ManagedPolicyUpdate, db: Session = Depends(get_db)):
    policy = get_policy(db, policy_id)
    if policy is None:
        raise _not_found("policy")
    try:
        return update_policy(db, policy, payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.post("/policies/{policy_id}/activate", response_model=ManagedPolicyRead)
def activate_policy(policy_id: uuid.UUID, db: Session = Depends(get_db)):
    policy = get_policy(db, policy_id)
    if policy is None:
        raise _not_found("policy")
    return update_policy(db, policy, {"status": "active"})


@router.post("/policies/{policy_id}/deactivate", response_model=ManagedPolicyRead)
def deactivate_policy(policy_id: uuid.UUID, db: Session = Depends(get_db)):
    policy = get_policy(db, policy_id)
    if policy is None:
        raise _not_found("policy")
    return update_policy(db, policy, {"status": "inactive"})


@router.get("/role-assignments", response_model=list[ManagedRoleAssignmentRead])
def read_role_assignments(
    organization_id: uuid.UUID | None = Query(default=None),
    principal_type: str | None = Query(default=None),
    principal_id: str | None = Query(default=None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_role_assignments(
        db,
        organization_id=organization_id,
        principal_type=principal_type,
        principal_id=principal_id,
        skip=skip,
        limit=limit,
    )


@router.post("/role-assignments", response_model=ManagedRoleAssignmentRead, status_code=status.HTTP_201_CREATED)
def add_role_assignment(payload: ManagedRoleAssignmentCreate, db: Session = Depends(get_db)):
    if get_role(db, payload.role_id) is None:
        raise _not_found("role")
    try:
        return create_role_assignment(db, payload.model_dump())
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.patch("/role-assignments/{assignment_id}", response_model=ManagedRoleAssignmentRead)
def edit_role_assignment(
    assignment_id: uuid.UUID,
    payload: ManagedRoleAssignmentUpdate,
    db: Session = Depends(get_db),
):
    assignment = get_assignment(db, assignment_id)
    if assignment is None:
        raise _not_found("role assignment")
    if payload.role_id is not None and get_role(db, payload.role_id) is None:
        raise _not_found("role")
    try:
        return update_role_assignment(db, assignment, payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        raise _conflict(exc) from exc


@router.post("/role-assignments/{assignment_id}/activate", response_model=ManagedRoleAssignmentRead)
def activate_role_assignment(assignment_id: uuid.UUID, db: Session = Depends(get_db)):
    assignment = get_assignment(db, assignment_id)
    if assignment is None:
        raise _not_found("role assignment")
    return update_role_assignment(db, assignment, {"status": "active"})


@router.post("/role-assignments/{assignment_id}/deactivate", response_model=ManagedRoleAssignmentRead)
def deactivate_role_assignment(assignment_id: uuid.UUID, db: Session = Depends(get_db)):
    assignment = get_assignment(db, assignment_id)
    if assignment is None:
        raise _not_found("role assignment")
    return update_role_assignment(db, assignment, {"status": "inactive"})


@router.post("/principals/resolve-permissions", response_model=PrincipalPermissionResolutionResponse)
def resolve_permissions(payload: PrincipalPermissionResolutionRequest, db: Session = Depends(get_db)):
    try:
        return resolve_principal_permissions(
            db,
            principal_type=payload.principal_type,
            principal_id=payload.principal_id,
            organization_id=payload.organization_id,
            scope=payload.scope,
            scope_id=payload.scope_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
