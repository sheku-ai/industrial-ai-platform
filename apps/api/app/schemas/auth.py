from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1_024)
    remember_me: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1_024)
    new_password: str = Field(min_length=1, max_length=1_024)


class AuthUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    status: str
    must_change_password: bool


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    role_id: uuid.UUID
    status: str


class SessionRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    remember_me: bool


class ManagedSessionRead(SessionRead):
    current: bool
    revoked_at: datetime | None
    revocation_reason: str | None
    client_ip: str | None
    user_agent: str | None
    status: str


class SessionPageRead(BaseModel):
    sessions: list[ManagedSessionRead]
    total: int
    offset: int
    limit: int
    status_filter: Literal["all", "active", "expired", "revoked"]


class SessionPolicyPublicRead(BaseModel):
    remember_me_enabled: bool


class AuthMeResponse(BaseModel):
    user: AuthUserRead
    session: SessionRead
    memberships: list[MembershipRead]


class LoginResponse(AuthMeResponse):
    authenticated: bool = True


class CsrfTokenResponse(BaseModel):
    csrf_token: str
    header_name: str


class PasswordChangedResponse(BaseModel):
    password_changed: bool = True
    all_sessions_revoked: bool = True
    reauthentication_required: bool = True
