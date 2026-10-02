from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime_worker import RuntimeWorker
from app.services.runtime_worker_audit import record_worker_transition


class RuntimeWorkerControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeWorkerControlDecision:
    desired_state: str
    observed_state: str
    accepts_work: bool
    should_exit: bool


class RuntimeWorkerControl:
    """Coordinates persistent desired-state commands and worker decisions."""

    ALLOWED_DESIRED_STATES = frozenset({"active", "paused", "draining", "disabled"})

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        if not callable(session_factory):
            raise ValueError("session_factory is required")
        self._session_factory = session_factory

    def set_desired_state(
        self,
        *,
        worker_key: str,
        desired_state: str,
        organization_id: UUID | None = None,
        actor_id: str | None = None,
    ) -> RuntimeWorker:
        worker_key = self._required(worker_key, "worker_key")
        desired_state = self._required(desired_state, "desired_state")
        if desired_state not in self.ALLOWED_DESIRED_STATES:
            raise ValueError(f"unsupported desired_state: {desired_state}")

        with self._session_factory() as session:
            worker = session.scalar(
                select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key).with_for_update()
            )
            if worker is None:
                raise RuntimeWorkerControlError(f"worker is not registered: {worker_key}")

            previous = worker.desired_state
            if previous != desired_state:
                worker.desired_state = desired_state
                record_worker_transition(
                    session,
                    worker=worker,
                    action="desired_state_changed",
                    before_state={"desired_state": previous},
                    after_state={"desired_state": desired_state},
                    actor_type="principal" if actor_id else "system",
                    actor_id=actor_id,
                    organization_id=organization_id,
                    metadata={
                        "previous_desired_state": previous,
                        "desired_state": desired_state,
                    },
                )
            session.commit()
            session.refresh(worker)
            return worker

    def decision(self, *, worker_key: str, instance_id: str) -> RuntimeWorkerControlDecision:
        worker_key = self._required(worker_key, "worker_key")
        instance_id = self._required(instance_id, "instance_id")

        with self._session_factory() as session:
            worker = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key))
            if worker is None:
                raise RuntimeWorkerControlError(f"worker is not registered: {worker_key}")
            if worker.instance_id != instance_id:
                raise RuntimeWorkerControlError(f"worker instance mismatch for {worker_key}")

            mapping = {
                "active": RuntimeWorkerControlDecision(
                    desired_state="active",
                    observed_state="ready",
                    accepts_work=True,
                    should_exit=False,
                ),
                "paused": RuntimeWorkerControlDecision(
                    desired_state="paused",
                    observed_state="paused",
                    accepts_work=False,
                    should_exit=False,
                ),
                "draining": RuntimeWorkerControlDecision(
                    desired_state="draining",
                    observed_state="draining",
                    accepts_work=False,
                    should_exit=False,
                ),
                "disabled": RuntimeWorkerControlDecision(
                    desired_state="disabled",
                    observed_state="offline",
                    accepts_work=False,
                    should_exit=False,
                ),
            }
            try:
                return mapping[worker.desired_state]
            except KeyError as exc:
                raise RuntimeWorkerControlError(f"unsupported persisted desired_state: {worker.desired_state}") from exc

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized
