from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OrganizationUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    role_id: uuid.UUID


class OrganizationMembershipUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


class OrganizationUserRead(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    display_name: str | None = None
    identity_type: str
    identity_status: str
    membership_status: str
    primary_role_id: uuid.UUID
    roles: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OrganizationRoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class OrganizationRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class OrganizationRoleDuplicate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class OrganizationRoleAssignmentCreate(BaseModel):
    membership_id: uuid.UUID
    role_id: uuid.UUID


class OrganizationPolicyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    effect: str = Field(default="deny", pattern="^(allow|deny)$")
    rules: dict[str, Any] = Field(default_factory=dict)


class OrganizationPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    effect: str | None = Field(default=None, pattern="^(allow|deny)$")
    rules: dict[str, Any] | None = None


class OrganizationAccessRuntimeResponse(BaseModel):
    runtime_name: str = "organization_access_management"
    runtime_status: str
    organization_id: uuid.UUID
    users: list[dict[str, Any]] = Field(default_factory=list)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    non_delegable_permissions: list[dict[str, Any]] = Field(default_factory=list)
    policies: list[dict[str, Any]] = Field(default_factory=list)
    assignments: list[dict[str, Any]] = Field(default_factory=list)
    technical_principals: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    postgresql_source_of_truth: bool = True
