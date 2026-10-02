from datetime import datetime

from pydantic import BaseModel


class RuntimeWorkerSummaryRead(BaseModel):
    calculated_at: datetime
    total_workers: int
    active_desired: int
    paused_desired: int
    draining_desired: int
    disabled_desired: int
    ready_workers: int
    accepting_work: int
    stale_workers: int
    failed_workers: int
    offline_workers: int
    busy_workers: int
    degraded_workers: int
    available_capacity_ratio: float
