from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.operational_health_issue import OperationalHealthIssue

HealthStatus = Literal["healthy", "degraded", "critical", "unknown"]


class HealthSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    organization_id: UUID
    overall_status: HealthStatus
    active_issues: int
    calculated_at: datetime


class SchedulerHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled_jobs: int
    disabled_jobs: int
    enabled_schedules: int
    overdue_schedules: int
    schedules_without_next_run: int
    pending_runs: int
    active_runs: int
    failed_runs: int
    oldest_pending_run_at: datetime | None
    expired_claims: int
    latest_success_at: datetime | None
    latest_failure_at: datetime | None


class RuntimeHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    pending_executions: int
    running_executions: int
    retryable_executions: int
    failed_executions: int
    dead_letter_executions: int
    cancelled_executions: int
    oldest_non_terminal_execution_at: datetime | None
    expired_leases: int
    stale_attempts: int


class ArtifactPublicationHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    reserved: int
    publishing: int
    published: int
    verified: int
    missing: int
    checksum_conflict: int
    failed: int
    oldest_unverified_publication_at: datetime | None


class ReconciliationHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    candidate_count: int
    oldest_candidate_at: datetime | None
    missing_candidates: int
    checksum_conflict_candidates: int
    last_manual_run_at: datetime | None
    last_successful_run_at: datetime | None
    last_failed_run_at: datetime | None


class HealthFreshness(BaseModel):
    model_config = ConfigDict(frozen=True)
    calculated_at: datetime
    data_max_timestamp: datetime | None
    age_seconds: int | None
    is_stale: bool


class OperationalHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    summary: HealthSummary
    scheduler: SchedulerHealth
    issues: list[OperationalHealthIssue] = []
    runtime: RuntimeHealth
    artifact_publications: ArtifactPublicationHealth
    reconciliation: ReconciliationHealth
    freshness: HealthFreshness
