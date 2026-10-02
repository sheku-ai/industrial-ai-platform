from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.runtime import RuntimeExecutionAttempt
from app.services.runtime_lifecycle import RuntimeLifecycleService


@dataclass(frozen=True)
class RuntimeWorkItem:
    organization_id: UUID
    execution_id: UUID
    execution_type: str
    subject_type: str
    subject_id: UUID
    attempt_id: UUID
    attempt_number: int
    lease_token: UUID
    input_payload: dict[str, Any]
    policy_snapshot: dict[str, Any]


@dataclass(frozen=True)
class RuntimeAdapterResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    continue_execution: bool = False


class RuntimeExecutionAdapter(Protocol):
    execution_type: str

    def execute(self, item: RuntimeWorkItem, heartbeat: RuntimeHeartbeat) -> RuntimeAdapterResult: ...


class RuntimeAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeExecutionAdapter] = {}

    def register(self, adapter: RuntimeExecutionAdapter) -> None:
        if not adapter.execution_type:
            raise ValueError("adapter execution_type is required")
        if adapter.execution_type in self._adapters:
            raise ValueError(f"adapter already registered for {adapter.execution_type}")
        self._adapters[adapter.execution_type] = adapter

    def resolve(self, execution_type: str) -> RuntimeExecutionAdapter | None:
        return self._adapters.get(execution_type)


class RuntimeHeartbeat:
    def __init__(
        self,
        lifecycle: RuntimeLifecycleService,
        organization_id: UUID,
        execution_id: UUID,
        lease_token: UUID,
        extend_by: timedelta,
    ) -> None:
        self.lifecycle = lifecycle
        self.organization_id = organization_id
        self.execution_id = execution_id
        self.lease_token = lease_token
        self.extend_by = extend_by

    def pulse(self) -> RuntimeExecutionAttempt:
        return self.lifecycle.heartbeat(
            self.organization_id,
            self.execution_id,
            lease_token=self.lease_token,
            extend_by=self.extend_by,
        )


class RuntimeWorkerService:
    """Provider-neutral worker boundary."""

    def __init__(
        self,
        session: Session,
        registry: RuntimeAdapterRegistry,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=5),
        heartbeat_extension: timedelta = timedelta(minutes=5),
    ) -> None:
        self.session = session
        self.registry = registry
        self.worker_id = worker_id
        self.lease_duration = lease_duration
        self.heartbeat_extension = heartbeat_extension
        self.lifecycle = RuntimeLifecycleService(session)
