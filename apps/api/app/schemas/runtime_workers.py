from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

WorkerDesiredState = Literal["active", "paused", "draining", "disabled"]
WorkerResourceScope = Literal["platform", "organization", "workload"]


class RuntimeWorkerPersistentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worker_key: str
    instance_id: str
    worker_type: str
    runtime_version: str | None
    desired_state: WorkerDesiredState
    observed_state: str
    capabilities: list[Any]
    queue_keys: list[Any]
    workload_classes: list[Any]
    active_configuration_revision_id: UUID | None
    started_at: datetime
    ready_at: datetime | None
    heartbeat_at: datetime | None
    last_seen_at: datetime | None
    metrics: dict[str, Any]
    last_error_code: str | None
    last_error_message: str | None
    updated_at: datetime


class RuntimeWorkerRead(RuntimeWorkerPersistentRead):
    resource_scope: WorkerResourceScope
    organization_id: UUID | None
    heartbeat_stale: bool
    heartbeat_stale_after_seconds: int
    accepting_work: bool
    ready: bool


class RuntimeWorkerDesiredStateUpdate(BaseModel):
    desired_state: WorkerDesiredState
