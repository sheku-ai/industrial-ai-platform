from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OperationalJobCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    operation_type: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    concurrency_policy: str = "forbid_overlap"
    misfire_policy: str = "skip"
    max_concurrent_runs: int = Field(default=1, ge=1)
    max_runtime_seconds: int | None = Field(default=None, ge=1)


class OperationalJobUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    operation_type: str | None = Field(default=None, min_length=1, max_length=128)
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None
    concurrency_policy: str | None = None
    misfire_policy: str | None = None
    max_concurrent_runs: int | None = Field(default=None, ge=1)
    max_runtime_seconds: int | None = Field(default=None, ge=1)


class OperationalJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    code: str
    name: str
    description: str | None
    operation_type: str
    parameters: dict[str, Any]
    enabled: bool
    concurrency_policy: str
    misfire_policy: str
    max_concurrent_runs: int
    max_runtime_seconds: int | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
