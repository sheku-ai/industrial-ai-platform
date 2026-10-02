from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AcceptanceExecutionCreate(BaseModel):
    execution_key: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    scenario: str = Field(default="local_product_acceptance", min_length=1, max_length=128)
    status: str = "PENDING"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    organization_id: uuid.UUID | None = None
    preserve_requested: bool = False
    reuse_requested: bool = False
    cleanup_requested: bool = False
    report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)


class AcceptanceExecutionUpdate(BaseModel):
    status: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    organization_id: uuid.UUID | None = None
    preserve_requested: bool | None = None
    reuse_requested: bool | None = None
    cleanup_requested: bool | None = None
    report: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] | None = None
    blockers: list[dict[str, Any]] | None = None


class AcceptanceGateUpsert(BaseModel):
    phase_code: str = Field(min_length=1, max_length=128)
    gate_code: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = None


class AcceptanceResourceUpsert(BaseModel):
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    external_ref: str = Field(min_length=1, max_length=255)
    created_by_execution: bool = False
    reused: bool = False
    cleanup_status: str = Field(default="not_requested", max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)


class AcceptanceGateRead(AcceptanceGateUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AcceptanceResourceRead(AcceptanceResourceUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AcceptanceExecutionRead(AcceptanceExecutionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    gates: list[AcceptanceGateRead] = Field(default_factory=list)
    resources: list[AcceptanceResourceRead] = Field(default_factory=list)


class AcceptanceExecutionListResponse(BaseModel):
    executions: list[AcceptanceExecutionRead]
    count: int
    postgresql_source_of_truth: bool = True
