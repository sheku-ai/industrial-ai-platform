from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime_worker import RuntimeWorker


class RuntimeWorkerRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeWorkerRegistration:
    worker_key: str
    instance_id: str
    worker_type: str
    runtime_version: str | None = None
    capabilities: tuple[str, ...] = ()
    queue_keys: tuple[str, ...] = ()
    workload_classes: tuple[str, ...] = ()
    active_configuration_revision_id: Any | None = None
    metadata: dict[str, Any] | None = None


class RuntimeWorkerRegistry:
    """Persistent lifecycle registry for generic platform workers."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session_factory is required")
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def register(self, registration: RuntimeWorkerRegistration) -> RuntimeWorker:
        worker_key = self._required(registration.worker_key, "worker_key")
        instance_id = self._required(registration.instance_id, "instance_id")
        worker_type = self._required(registration.worker_type, "worker_type")
        now = self._clock()

        with self._session_factory() as session:
            worker = session.scalar(
                select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key).with_for_update()
            )
            if worker is None:
                worker = RuntimeWorker(
                    worker_key=worker_key,
                    instance_id=instance_id,
                    worker_type=worker_type,
                    started_at=now,
                )
                session.add(worker)
            elif worker.instance_id != instance_id:
                duplicate = session.scalar(
                    select(RuntimeWorker.id).where(
                        RuntimeWorker.instance_id == instance_id,
                        RuntimeWorker.id != worker.id,
                    )
                )
                if duplicate is not None:
                    raise RuntimeWorkerRegistryError(f"worker instance is already registered: {instance_id}")
                worker.instance_id = instance_id
                worker.started_at = now
                worker.ready_at = None

            worker.worker_type = worker_type
            worker.runtime_version = self._optional(registration.runtime_version)
            worker.capabilities = self._normalized_values(registration.capabilities)
            worker.queue_keys = self._normalized_values(registration.queue_keys)
            worker.workload_classes = self._normalized_values(registration.workload_classes)
            worker.active_configuration_revision_id = registration.active_configuration_revision_id
            worker.metadata_ = dict(registration.metadata or {})
            worker.observed_state = "starting"
            worker.heartbeat_at = now
            worker.last_seen_at = now
            worker.last_error_code = None
            worker.last_error_message = None
            session.commit()
            session.refresh(worker)
            return worker

    def heartbeat(
        self,
        *,
        worker_key: str,
        instance_id: str,
        observed_state: str = "ready",
        metrics: dict[str, Any] | None = None,
        active_configuration_revision_id: Any | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> RuntimeWorker:
        worker_key = self._required(worker_key, "worker_key")
        instance_id = self._required(instance_id, "instance_id")
        now = self._clock()

        with self._session_factory() as session:
            worker = session.scalar(
                select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key).with_for_update()
            )
            if worker is None:
                raise RuntimeWorkerRegistryError(f"worker is not registered: {worker_key}")
            if worker.instance_id != instance_id:
                raise RuntimeWorkerRegistryError(f"worker instance mismatch for {worker_key}")

            worker.observed_state = observed_state
            worker.heartbeat_at = now
            worker.last_seen_at = now
            if observed_state == "ready" and worker.ready_at is None:
                worker.ready_at = now
            if metrics is not None:
                worker.metrics = dict(metrics)
            if active_configuration_revision_id is not None:
                worker.active_configuration_revision_id = active_configuration_revision_id
            worker.last_error_code = self._optional(error_code)
            worker.last_error_message = self._optional(error_message)
            session.commit()
            session.refresh(worker)
            return worker

    def mark_offline(
        self,
        *,
        worker_key: str,
        instance_id: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> RuntimeWorker:
        worker_key = self._required(worker_key, "worker_key")
        instance_id = self._required(instance_id, "instance_id")
        now = self._clock()

        with self._session_factory() as session:
            worker = session.scalar(
                select(RuntimeWorker).where(RuntimeWorker.worker_key == worker_key).with_for_update()
            )
            if worker is None:
                raise RuntimeWorkerRegistryError(f"worker is not registered: {worker_key}")
            if worker.instance_id != instance_id:
                raise RuntimeWorkerRegistryError(f"worker instance mismatch for {worker_key}")

            worker.observed_state = "failed" if error_code or error_message else "offline"
            worker.last_seen_at = now
            worker.last_error_code = self._optional(error_code)
            worker.last_error_message = self._optional(error_message)
            session.commit()
            session.refresh(worker)
            return worker

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized

    @staticmethod
    def _optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalized_values(values: Iterable[str]) -> list[str]:
        return sorted({value.strip() for value in values if value.strip()})
