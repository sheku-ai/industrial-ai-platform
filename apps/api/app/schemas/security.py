import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RoleCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_system: bool = False
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class RoleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_system: bool | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class RoleRead(RoleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class PermissionCreate(BaseModel):
    resource: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    description: str | None = None


class PermissionUpdate(BaseModel):
    resource: str | None = Field(default=None, min_length=1, max_length=128)
    action: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class PermissionRead(PermissionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class RolePermissionCreate(BaseModel):
    role_id: uuid.UUID
    permission_id: uuid.UUID


class RolePermissionUpdate(BaseModel):
    role_id: uuid.UUID | None = None
    permission_id: uuid.UUID | None = None


class RolePermissionRead(RolePermissionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class PolicyCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    effect: str = "allow"
    rules: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class PolicyUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    effect: str | None = None
    rules: dict[str, Any] | None = None
    status: str | None = None


class PolicyRead(PolicyCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class RoleAssignmentCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    role_id: uuid.UUID
    principal_type: str = Field(min_length=1, max_length=64)
    principal_id: str = Field(min_length=1, max_length=255)
    scope_type: str | None = None
    scope_id: str | None = None
    status: str = "active"


class RoleAssignmentUpdate(BaseModel):
    role_id: uuid.UUID | None = None
    principal_type: str | None = Field(default=None, min_length=1, max_length=64)
    principal_id: str | None = Field(default=None, min_length=1, max_length=255)
    scope_type: str | None = None
    scope_id: str | None = None
    status: str | None = None


class RoleAssignmentRead(RoleAssignmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
