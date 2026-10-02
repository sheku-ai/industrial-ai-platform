from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OperationalScheduleCreate(BaseModel):
    operational_job_id: UUID
    schedule_expression: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="UTC", min_length=1, max_length=128)
    enabled: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None


class OperationalScheduleUpdate(BaseModel):
    schedule_expression: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class OperationalScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    operational_job_id: UUID
    schedule_type: str
    schedule_expression: str
    timezone: str
    enabled: bool
    start_at: datetime | None
    end_at: datetime | None
    next_run_at: datetime | None
    last_evaluated_at: datetime | None
    schedule_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class SchedulerRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    operational_job_id: UUID
    schedule_id: UUID | None
    schedule_version: int | None
    trigger_type: str
    logical_run_key: str
    scheduled_for: datetime | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    parameters_snapshot: dict[str, Any]
    runtime_execution_id: UUID | None
    requested_by: str | None
    correlation_id: str | None
    outcome: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime


class SchedulerEvaluationRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    evaluated_at: datetime | None = None


class SchedulerEvaluationResponse(BaseModel):
    evaluated_at: datetime
    scanned: int
    due: int
    created: int
    skipped: int
    next_runs_updated: int
    run_ids: list[UUID]
