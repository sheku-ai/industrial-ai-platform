from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

DependencyStatus = Literal["healthy", "unavailable", "disabled", "not_configured", "configured"]
DependencyLifecycleState = Literal["alive", "ready", "degraded", "unavailable"]


class DependencyHealthItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    required: bool
    enabled: bool
    status: DependencyStatus
    lifecycle_state: DependencyLifecycleState
    detail: str | None = None


class DependencyHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["healthy", "degraded", "critical"]
    checked_at: datetime
    dependencies: list[DependencyHealthItem]


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "not_ready"]
    lifecycle_state: Literal["ready", "unavailable"]
    checked_at: datetime
    required_dependencies: list[DependencyHealthItem]
