from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.auth import SessionPageRead


class SessionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    status: str
    version: int
    idle_timeout_seconds: int
    absolute_timeout_seconds: int
    max_concurrent_sessions: int
    activity_write_interval_seconds: int
    remember_me_enabled: bool
    remember_idle_timeout_seconds: int
    remember_absolute_timeout_seconds: int
    retention_days: int
    updated_at: datetime
    updated_by: str | None


class SessionPolicyUpdate(BaseModel):
    idle_timeout_seconds: int = Field(ge=60, le=86_400)
    absolute_timeout_seconds: int = Field(ge=300, le=2_592_000)
    max_concurrent_sessions: int = Field(ge=1, le=100)
    activity_write_interval_seconds: int = Field(ge=30, le=3_600)
    remember_me_enabled: bool
    remember_idle_timeout_seconds: int = Field(ge=60, le=604_800)
    remember_absolute_timeout_seconds: int = Field(ge=300, le=31_536_000)
    retention_days: int = Field(ge=1, le=3_650)
    application_mode: Literal["new_sessions_only", "restrict_existing"] = "new_sessions_only"

    @model_validator(mode="after")
    def coherent_expirations(self):
        if self.idle_timeout_seconds > self.absolute_timeout_seconds:
            raise ValueError("idle_timeout_must_not_exceed_absolute_timeout")
        if self.remember_idle_timeout_seconds > self.remember_absolute_timeout_seconds:
            raise ValueError("remember_idle_timeout_must_not_exceed_absolute_timeout")
        if self.activity_write_interval_seconds >= self.idle_timeout_seconds:
            raise ValueError("activity_write_interval_must_be_shorter_than_idle_timeout")
        if self.activity_write_interval_seconds >= self.remember_idle_timeout_seconds:
            raise ValueError("activity_write_interval_must_be_shorter_than_remember_idle_timeout")
        return self


class UserSessionsRead(SessionPageRead):
    user_id: uuid.UUID


class SessionMutationRead(BaseModel):
    operation: str
    outcome: Literal["updated", "unchanged"]
    revoked_session_count: int
