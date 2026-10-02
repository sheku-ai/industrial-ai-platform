from __future__ import annotations

import contextlib
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.runtime_dependency_recovery import (
    RuntimeDependencyRecovery,
    is_transient_dependency_error,
)
from app.services.runtime_worker_control import RuntimeWorkerControl
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry


@dataclass(frozen=True)
class RuntimeManagedServiceConfiguration:
    worker_key: str
    worker_type: str
    capabilities: tuple[str, ...]
    poll_interval_seconds: float
    heartbeat_interval_seconds: float
    runtime_version: str | None = None


class RuntimeManagedService:
    """Runs a generic persistent platform service under worker control-plane management."""

    def __init__(
        self,
        session_factory: Callable,
        configuration: RuntimeManagedServiceConfiguration,
        cycle: Callable[[], dict[str, Any] | None],
        recovery: RuntimeDependencyRecovery | None = None,
    ) -> None:
        self._registry = RuntimeWorkerRegistry(session_factory)
        self._control = RuntimeWorkerControl(session_factory)
        self._configuration = configuration
        self._cycle = cycle
        self._recovery = recovery or RuntimeDependencyRecovery()
        hostname = socket.gethostname()
        self._instance_id = os.getenv("WORKER_INSTANCE_ID") or (f"{configuration.worker_key}:{hostname}:{os.getpid()}")
        self._metadata = {"hostname": hostname, "process_id": os.getpid()}

    def run_forever(self) -> int:
        while True:
            try:
                result = self._run_registered()
                self._recovery.recovered()
                return result
            except KeyboardInterrupt:
                return self._mark_offline()
            except Exception as exc:
                if not is_transient_dependency_error(exc):
                    self._mark_failed(exc)
                    raise
                self._recovery.wait()

    def _run_registered(self) -> int:
        config = self._configuration
        self._registry.register(
            RuntimeWorkerRegistration(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
                worker_type=config.worker_type,
                runtime_version=config.runtime_version,
                capabilities=config.capabilities,
                metadata=self._metadata,
            )
        )
        self._recovery.recovered()
        self._registry.heartbeat(
            worker_key=config.worker_key,
            instance_id=self._instance_id,
            observed_state="ready",
            metrics={"cycle_count": 0},
        )
        next_heartbeat = time.monotonic() + config.heartbeat_interval_seconds
        cycle_count = 0
        last_metrics: dict[str, Any] = {"cycle_count": 0}

        while True:
            decision = self._control.decision(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
            )
            now = time.monotonic()
            if not decision.accepts_work:
                if now >= next_heartbeat:
                    self._registry.heartbeat(
                        worker_key=config.worker_key,
                        instance_id=self._instance_id,
                        observed_state=decision.observed_state,
                        metrics=last_metrics,
                    )
                    next_heartbeat = now + config.heartbeat_interval_seconds
                time.sleep(config.poll_interval_seconds)
                continue

            self._registry.heartbeat(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
                observed_state="busy",
                metrics=last_metrics,
            )
            cycle_metrics = self._cycle() or {}
            cycle_count += 1
            last_metrics = {"cycle_count": cycle_count, **cycle_metrics}
            post_cycle = self._control.decision(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
            )
            self._registry.heartbeat(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
                observed_state=post_cycle.observed_state,
                metrics=last_metrics,
            )
            next_heartbeat = time.monotonic() + config.heartbeat_interval_seconds
            time.sleep(config.poll_interval_seconds)

    def _mark_offline(self) -> int:
        config = self._configuration
        with contextlib.suppress(Exception):
            self._registry.mark_offline(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
            )
        return 0

    def _mark_failed(self, exc: Exception) -> None:
        config = self._configuration
        with contextlib.suppress(Exception):
            self._registry.heartbeat(
                worker_key=config.worker_key,
                instance_id=self._instance_id,
                observed_state="failed",
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
