from __future__ import annotations

import logging
import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerRun
from app.models.runtime import RuntimeExecution
from app.services.runtime_dependency_recovery import (
    RuntimeDependencyRecovery,
    is_transient_dependency_error,
)
from app.services.runtime_worker_contracts import (
    SCHEDULER_CAPABILITIES,
    SCHEDULER_WORKER_TYPE,
)
from app.services.runtime_worker_registry import (
    RuntimeWorkerRegistration,
    RuntimeWorkerRegistry,
)
from app.services.scheduler_dispatch import SchedulerDispatchService
from app.services.scheduler_evaluation import SchedulerEvaluationService
from app.services.scheduler_runtime_sync import (
    TERMINAL_RUNTIME_STATUSES,
    SchedulerRuntimeSyncService,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerDaemonConfig:
    poll_interval_seconds: float = 5.0
    batch_limit: int = 100
    owner_id: str = "scheduler-daemon"

    @classmethod
    def from_environment(cls) -> SchedulerDaemonConfig:
        return cls(
            poll_interval_seconds=max(0.5, float(os.getenv("SCHEDULER_POLL_INTERVAL_SECONDS", "5"))),
            batch_limit=max(1, min(int(os.getenv("SCHEDULER_BATCH_LIMIT", "100")), 500)),
            owner_id=os.getenv("SCHEDULER_OWNER_ID", "scheduler-daemon"),
        )


class SchedulerDaemon:
    def __init__(
        self,
        *,
        config: SchedulerDaemonConfig,
        session_factory: Callable[[], Session],
        stop_event: threading.Event | None = None,
        instance_id: str | None = None,
        recovery: RuntimeDependencyRecovery | None = None,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.stop_event = stop_event or threading.Event()
        self.instance_id = instance_id or str(uuid4())
        self.started_at = datetime.now(UTC)
        self._registry = RuntimeWorkerRegistry(session_factory)
        self._recovery = recovery or RuntimeDependencyRecovery()
        self._registered = False
        self._metrics: dict[str, object] = {
            "cycles_completed": 0,
            "organizations_processed": 0,
            "runs_created": 0,
        }

    def request_stop(self, *_args) -> None:
        self.stop_event.set()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self.request_stop)

    def _write_state(
        self,
        *,
        cycles_increment: int = 0,
        organizations_increment: int = 0,
        runs_increment: int = 0,
        **values,
    ) -> None:
        datetime.now(UTC)
        try:
            self._ensure_registered()
            status_value = values.pop("status", "running")
            self._metrics["cycles_completed"] = int(self._metrics.get("cycles_completed", 0)) + cycles_increment
            self._metrics["organizations_processed"] = (
                int(self._metrics.get("organizations_processed", 0)) + organizations_increment
            )
            self._metrics["runs_created"] = int(self._metrics.get("runs_created", 0)) + runs_increment
            for key, value in values.items():
                self._metrics[key] = value.isoformat() if isinstance(value, datetime) else value

            observed_state = {
                "running": "busy" if values.get("last_cycle_started_at") else "ready",
                "degraded": "failed",
                "stopped": "offline",
            }.get(status_value, "failed")
            self._registry.heartbeat(
                worker_key=self.config.owner_id,
                instance_id=self.instance_id,
                observed_state=observed_state,
                metrics=dict(self._metrics),
                error_code=(str(values.get("last_error_type")) if values.get("last_error_type") else None),
                error_message=(str(values.get("last_error_message")) if values.get("last_error_message") else None),
            )
        except Exception:
            logger.exception("failed to persist scheduler worker state")
            raise

    def _ensure_registered(self) -> None:
        if self._registered:
            return
        worker = self._registry.register(
            RuntimeWorkerRegistration(
                worker_key=self.config.owner_id,
                instance_id=self.instance_id,
                worker_type=SCHEDULER_WORKER_TYPE,
                runtime_version=os.getenv("BUILD_COMMIT"),
                capabilities=SCHEDULER_CAPABILITIES,
                metadata={"service": "scheduler"},
            )
        )
        self._metrics.update(worker.metrics or {})
        self._registered = True

    def _work_organizations(self, now: datetime) -> tuple[UUID, ...]:
        session = self.session_factory()
        try:
            due_schedule_organizations = session.scalars(
                select(OperationalSchedule.organization_id)
                .join(
                    OperationalJob,
                    (OperationalJob.id == OperationalSchedule.operational_job_id)
                    & (OperationalJob.organization_id == OperationalSchedule.organization_id),
                )
                .where(
                    OperationalSchedule.enabled.is_(True),
                    OperationalJob.enabled.is_(True),
                    OperationalSchedule.next_run_at.is_not(None),
                    OperationalSchedule.next_run_at <= now,
                )
                .distinct()
            ).all()
            pending_run_organizations = session.scalars(
                select(SchedulerRun.organization_id)
                .join(
                    OperationalJob,
                    (OperationalJob.id == SchedulerRun.operational_job_id)
                    & (OperationalJob.organization_id == SchedulerRun.organization_id),
                )
                .where(
                    SchedulerRun.status == "pending",
                    OperationalJob.enabled.is_(True),
                )
                .distinct()
            ).all()
            completed_runtime_organizations = session.scalars(
                select(SchedulerRun.organization_id)
                .join(
                    RuntimeExecution,
                    (RuntimeExecution.id == SchedulerRun.runtime_execution_id)
                    & (RuntimeExecution.organization_id == SchedulerRun.organization_id),
                )
                .where(
                    SchedulerRun.status == "dispatched",
                    RuntimeExecution.status.in_(TERMINAL_RUNTIME_STATUSES),
                )
                .distinct()
            ).all()
            organizations = (
                set(due_schedule_organizations) | set(pending_run_organizations) | set(completed_runtime_organizations)
            )
            return tuple(sorted(organizations, key=str))
        finally:
            session.close()

    def run_cycle(self, *, evaluated_at: datetime | None = None) -> tuple[int, int]:
        now = evaluated_at or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        self._write_state(status="running", last_cycle_started_at=now)
        processed_organizations = 0
        runs_created = 0
        last_error: Exception | None = None

        for organization_id in self._work_organizations(now):
            if self.stop_event.is_set():
                break

            processed_organizations += 1

            evaluation_session = self.session_factory()
            try:
                evaluation = SchedulerEvaluationService(evaluation_session).evaluate_due(
                    organization_id,
                    limit=self.config.batch_limit,
                    evaluated_at=now,
                    requested_by=self.config.owner_id,
                )
                runs_created += evaluation.created
                logger.info(
                    "scheduler evaluation organization=%s scanned=%s created=%s skipped=%s",
                    organization_id,
                    evaluation.scanned,
                    evaluation.created,
                    evaluation.skipped,
                )
            except Exception as exc:
                evaluation_session.rollback()
                last_error = exc
                logger.exception("scheduler evaluation failed organization=%s", organization_id)
            finally:
                evaluation_session.close()

            dispatch_session = self.session_factory()
            try:
                dispatch = SchedulerDispatchService(dispatch_session).dispatch_pending(
                    organization_id,
                    limit=self.config.batch_limit,
                    dispatched_at=now,
                    dispatched_by=self.config.owner_id,
                )
                logger.info(
                    "scheduler dispatch organization=%s scanned=%s dispatched=%s skipped=%s cancelled_pending=%s",
                    organization_id,
                    dispatch.scanned,
                    dispatch.dispatched,
                    dispatch.skipped,
                    dispatch.cancelled_pending,
                )
            except Exception as exc:
                dispatch_session.rollback()
                last_error = exc
                logger.exception("scheduler dispatch failed organization=%s", organization_id)
            finally:
                dispatch_session.close()

            sync_session = self.session_factory()
            try:
                synchronized = SchedulerRuntimeSyncService(sync_session).synchronize(
                    organization_id,
                    limit=self.config.batch_limit,
                    synchronized_at=now,
                )
                logger.info(
                    "scheduler runtime sync organization=%s scanned=%s succeeded=%s failed=%s cancelled=%s",
                    organization_id,
                    synchronized.scanned,
                    synchronized.succeeded,
                    synchronized.failed,
                    synchronized.cancelled,
                )
            except Exception as exc:
                sync_session.rollback()
                last_error = exc
                logger.exception("scheduler runtime sync failed organization=%s", organization_id)
            finally:
                sync_session.close()

        completed_at = datetime.now(UTC)
        state_values = {"last_cycle_completed_at": completed_at}
        if last_error is None:
            state_values.update(
                {
                    "status": "running",
                    "last_success_at": completed_at,
                    "last_error_type": None,
                    "last_error_message": None,
                }
            )
        else:
            state_values.update(
                {
                    "status": "degraded",
                    "last_error_at": completed_at,
                    "last_error_type": type(last_error).__name__,
                    "last_error_message": str(last_error)[:4000],
                }
            )
        self._write_state(
            cycles_increment=1,
            organizations_increment=processed_organizations,
            runs_increment=runs_created,
            **state_values,
        )
        return processed_organizations, runs_created

    def run_forever(self) -> None:
        logger.info(
            "scheduler daemon started owner_id=%s instance_id=%s poll_interval_seconds=%s batch_limit=%s",
            self.config.owner_id,
            self.instance_id,
            self.config.poll_interval_seconds,
            self.config.batch_limit,
        )
        while not self.stop_event.is_set():
            try:
                self._write_state(status="running")
                self._recovery.recovered()
                self.run_cycle()
            except Exception as exc:
                logger.exception("scheduler cycle discovery failed")
                if not is_transient_dependency_error(exc):
                    self._write_state(
                        status="degraded",
                        last_error_at=datetime.now(UTC),
                        last_error_type=type(exc).__name__,
                        last_error_message=str(exc)[:4000],
                    )
                else:
                    self._registered = False
                    self._recovery.wait()
                    continue
            self.stop_event.wait(self.config.poll_interval_seconds)

        try:
            self._registry.mark_offline(
                worker_key=self.config.owner_id,
                instance_id=self.instance_id,
            )
        except Exception:
            logger.exception("failed to mark scheduler worker offline")
        logger.info("scheduler daemon stopped owner_id=%s instance_id=%s", self.config.owner_id, self.instance_id)


def build_scheduler_daemon() -> SchedulerDaemon:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")
    return SchedulerDaemon(
        config=SchedulerDaemonConfig.from_environment(),
        session_factory=SessionLocal,
    )
