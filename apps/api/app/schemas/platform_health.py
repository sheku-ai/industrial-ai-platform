from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PlatformHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["healthy", "degraded", "critical"]
    checked_at: datetime
    database: Literal["healthy", "unavailable"]
    scheduler: Literal["healthy", "degraded", "not_required", "unavailable"]
    enabled_schedules: int
    active_workers: int
    stale_workers: int
    degraded_workers: int = 0
    latest_heartbeat_at: datetime | None = None
    latest_cycle_started_at: datetime | None = None
    latest_cycle_completed_at: datetime | None = None
    scheduler_cycles_completed: int = 0
    scheduler_heartbeat_current: bool = False
    scheduler_loop_progressing: bool = False
    scheduler_execution_capable: bool = False
    detail: str | None = None
