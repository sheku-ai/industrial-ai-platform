"""Pipeline state transitions for Platform Worker."""

from __future__ import annotations

from app.services.worker.contracts import (
    JobLease,
    PipelineStateTransition,
    RetryDecision,
    WorkerExecutionResult,
    WorkerJobStatus,
)
from app.services.worker.interfaces import PipelineStateService


class DeterministicPipelineStateService(PipelineStateService):
    """Builds explicit state transitions for persisted worker jobs."""

    def to_running(self, lease: JobLease) -> PipelineStateTransition:
        return PipelineStateTransition(
            job_id=lease.job_id,
            from_status=lease.status,
            to_status=WorkerJobStatus.RUNNING,
            reason="worker_execution_started",
        )

    def from_result(self, lease: JobLease, result: WorkerExecutionResult) -> PipelineStateTransition:
        return PipelineStateTransition(
            job_id=lease.job_id,
            from_status=WorkerJobStatus.RUNNING,
            to_status=result.status,
            reason=result.message,
            metrics=result.metrics,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def from_retry_decision(self, lease: JobLease, decision: RetryDecision) -> PipelineStateTransition:
        return PipelineStateTransition(
            job_id=lease.job_id,
            from_status=WorkerJobStatus.RUNNING,
            to_status=decision.next_status,
            reason="retry_decision",
            metrics={
                "next_attempt_count": decision.next_attempt_count,
                "backoff_seconds": decision.backoff_seconds,
                "retryable": decision.retryable,
            },
            error_code=decision.error_code,
            error_message=decision.error_message,
        )
