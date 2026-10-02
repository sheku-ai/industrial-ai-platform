"""Platform Worker runtime orchestration boundary."""

from __future__ import annotations

from datetime import timedelta

from app.services.worker.contracts import WorkerExecutionContext, WorkerExecutionResult, WorkerJobStatus, WorkerNodeRef
from app.services.worker.interfaces import JobLeaseRepository, JobRoutingService, PlatformWorker, WorkerExecutor


class SingleJobPlatformWorker(PlatformWorker):
    """Executes at most one leased job.

    This class is intentionally process-agnostic. It can be used by a daemon,
    scheduled task, queue consumer, or managed worker service without changing
    the product boundary.
    """

    def __init__(
        self,
        leases: JobLeaseRepository,
        router: JobRoutingService,
        executor: WorkerExecutor,
        lease_duration: timedelta | None = None,
    ) -> None:
        self.leases = leases
        self.router = router
        self.executor = executor
        self.lease_duration = lease_duration or timedelta(minutes=15)

    def run_once(self, worker: WorkerNodeRef) -> WorkerExecutionResult | None:
        lease = self.leases.claim_next(worker=worker, lease_duration=self.lease_duration)
        if lease is None:
            return None

        if not self.router.can_execute(worker, lease):
            return WorkerExecutionResult(
                job_id=lease.job_id,
                status=WorkerJobStatus.FAILED_TERMINAL,
                error_code="worker_capability_mismatch",
                error_message="Worker node cannot execute the leased job type or pipeline.",
            )

        context = WorkerExecutionContext(worker=worker, lease=lease)
        return self.executor.execute(context)
