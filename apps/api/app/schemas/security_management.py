import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SecurityManagementReadiness(BaseModel):
    roles_count: int
    permissions_count: int
    policies_count: int
    assignments_count: int
    active_roles_count: int
    active_permissions_count: int
    active_policies_count: int
    active_assignments_count: int
    has_roles: bool
    has_permissions: bool
    has_assignments: bool
    security_management_ready: bool
    authentication_provider_ready: bool = False
    jwt_ready: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    postgresql_source_of_truth: bool = True


class ManagedRoleCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_system: bool = False
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class ManagedRoleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_system: bool | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class ManagedRoleRead(ManagedRoleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class GlobalRoleReconcileRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    permission_keys: list[str] = Field(min_length=1)


class GlobalRoleRead(BaseModel):
    role_id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    scope: Literal["platform"] = "platform"
    status: str
    is_system: bool
    configurable: bool
    permission_keys: list[str]
    outcome: Literal["created", "idempotent"] | None = None


class GlobalRoleStatusRead(GlobalRoleRead):
    outcome: Literal["updated", "idempotent"]


class GlobalUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    temporary_password: str = Field(min_length=1, max_length=1_024)


class GlobalUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=320)


class GlobalPasswordReset(BaseModel):
    temporary_password: str = Field(min_length=1, max_length=1_024)


class GlobalMembershipMutation(BaseModel):
    role_id: uuid.UUID


class GlobalUserRead(BaseModel):
    user_id: uuid.UUID
    username: str = Field(min_length=1)
    display_name: str | None
    email: str = Field(min_length=1)
    status: str
    must_change_password: bool
    active_sessions: int
    global_roles: list[dict[str, Any]]
    memberships: list[dict[str, Any]]


class GlobalUserRuntime(BaseModel):
    users: list[GlobalUserRead]
    organizations: list[dict[str, Any]]
    global_roles: list[dict[str, Any]]
    organization_roles: list[dict[str, Any]]
    capabilities: dict[str, bool]
    postgresql_source_of_truth: bool = True


class GlobalUserMutationResult(BaseModel):
    operation: str
    outcome: str
    user: GlobalUserRead | None = None


class ManagedPermissionCreate(BaseModel):
    resource: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    description: str | None = None


class ManagedPermissionRead(ManagedPermissionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ManagedRolePermissionRead(BaseModel):
    id: uuid.UUID
    role_id: uuid.UUID
    permission_id: uuid.UUID
    permission: ManagedPermissionRead
    attached: bool
    created_at: datetime
    updated_at: datetime


class ManagedPolicyCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    effect: str = "allow"
    rules: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class ManagedPolicyUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    effect: str | None = None
    rules: dict[str, Any] | None = None
    status: str | None = None


class ManagedPolicyRead(ManagedPolicyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class ManagedRoleAssignmentCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    role_id: uuid.UUID
    principal_type: str = Field(min_length=1, max_length=64)
    principal_id: str = Field(min_length=1, max_length=255)
    scope_type: str | None = None
    scope_id: str | None = None
    status: str = "active"


class ManagedRoleAssignmentUpdate(BaseModel):
    role_id: uuid.UUID | None = None
    principal_type: str | None = Field(default=None, min_length=1, max_length=64)
    principal_id: str | None = Field(default=None, min_length=1, max_length=255)
    scope_type: str | None = None
    scope_id: str | None = None
    status: str | None = None


class ManagedRoleAssignmentRead(ManagedRoleAssignmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class PrincipalPermissionResolutionRequest(BaseModel):
    principal_type: str = Field(default="user", min_length=1, max_length=64)
    principal_id: str = Field(min_length=1, max_length=255)
    organization_id: uuid.UUID | None = None
    scope: str = Field(default="organization", min_length=1, max_length=64)
    scope_id: str | None = None


class PrincipalRoleSummary(BaseModel):
    role_id: uuid.UUID
    code: str
    name: str
    status: str
    organization_id: uuid.UUID | None = None


class PrincipalAssignmentSummary(BaseModel):
    assignment_id: uuid.UUID
    role_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    principal_type: str
    principal_id: str
    scope_type: str | None = None
    scope_id: str | None = None
    status: str


class PrincipalPermissionResolutionResponse(BaseModel):
    principal_type: str
    principal_id: str
    organization_id: uuid.UUID | None = None
    scope: str
    scope_id: str | None = None
    permissions: list[str]
    roles: list[PrincipalRoleSummary]
    assignments: list[PrincipalAssignmentSummary]
    policies_applied: list[str]
    access_management_ready: bool
    jwt_required: bool = False
    jwt_used: bool = False
    llm_used: bool = False
    embeddings_used: bool = False
    qdrant_used: bool = False
    postgresql_source_of_truth: bool = True
