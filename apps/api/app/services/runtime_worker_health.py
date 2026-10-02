from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_audit import record_worker_transition


@dataclass(frozen=True)
class RuntimeWorkerReadiness:
    worker_key: str
    desired_state: str
    observed_state: str
    heartbeat_stale: bool
    accepting_work: bool
    ready: bool


class RuntimeWorkerHealthService:
    """Evaluates worker readiness and reconciles stale heartbeat state."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        stale_after_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session_factory is required")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self._session_factory = session_factory
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, worker: RuntimeWorker) -> RuntimeWorkerReadiness:
        now = self._clock()
        heartbeat_stale = worker.heartbeat_at is None or worker.heartbeat_at < now - self._stale_after
        accepting_work = (
            worker.desired_state == "active" and worker.observed_state in {"ready", "busy"} and not heartbeat_stale
        )
        return RuntimeWorkerReadiness(
            worker_key=worker.worker_key,
            desired_state=worker.desired_state,
            observed_state=worker.observed_state,
            heartbeat_stale=heartbeat_stale,
            accepting_work=accepting_work,
            ready=accepting_work,
        )

    def reconcile_stale(self, *, batch_limit: int = 100) -> list[str]:
        if batch_limit <= 0:
            raise ValueError("batch_limit must be positive")

        now = self._clock()
        cutoff = now - self._stale_after
        with self._session_factory() as session:
            workers = list(
                session.scalars(
                    select(RuntimeWorker)
                    .where(
                        RuntimeWorker.observed_state.notin_(["offline", "failed"]),
                        or_(
                            RuntimeWorker.heartbeat_at.is_(None),
                            RuntimeWorker.heartbeat_at < cutoff,
                        ),
                    )
                    .order_by(RuntimeWorker.heartbeat_at.asc().nullsfirst())
                    .limit(batch_limit)
                    .with_for_update(skip_locked=True)
                ).all()
            )

            reconciled: list[str] = []
            for worker in workers:
                previous_state = worker.observed_state
                worker.observed_state = "offline"
                worker.last_error_code = "heartbeat_stale"
                worker.last_error_message = (
                    f"worker heartbeat exceeded {int(self._stale_after.total_seconds())} seconds"
                )
                record_worker_transition(
                    session,
                    worker=worker,
                    action="heartbeat_stale_reconciled",
                    before_state={
                        "observed_state": previous_state,
                        "heartbeat_at": worker.heartbeat_at.isoformat() if worker.heartbeat_at else None,
                    },
                    after_state={
                        "observed_state": "offline",
                        "last_error_code": "heartbeat_stale",
                    },
                    actor_type="system",
                    actor_id="runtime-worker-monitor",
                    metadata={"heartbeat_stale_after_seconds": int(self._stale_after.total_seconds())},
                )
                reconciled.append(worker.worker_key)

            session.commit()
            return reconciled
