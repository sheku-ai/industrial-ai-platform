from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.orchestration.base import ExecutionState, FailureCategory, FallbackReason

JsonMapping = Mapping[str, Any]


class RuntimeAuditAction(StrEnum):
    EXECUTION_RECEIVED = "runtime.execution.received"
    EXECUTION_REJECTED = "runtime.execution.rejected"
    EXECUTION_STATE_CHANGED = "runtime.execution.state_changed"
    EXECUTION_ATTEMPTED = "runtime.execution.attempted"
    EXECUTION_RETRIED = "runtime.execution.retried"
    EXECUTION_COMPLETED = "runtime.execution.completed"
    EXECUTION_FALLBACK_COMPLETED = "runtime.execution.fallback_completed"
    EXECUTION_FAILED = "runtime.execution.failed"
    EXECUTION_CANCELLED = "runtime.execution.cancelled"
    EXECUTION_TIMED_OUT = "runtime.execution.timed_out"
    DUPLICATE_PREVENTED = "runtime.execution.duplicate_prevented"


@dataclass(frozen=True)
class RuntimeAuditEvent:
    event_id: uuid.UUID
    occurred_at: datetime
    action: RuntimeAuditAction
    request_id: uuid.UUID
    organization_id: uuid.UUID | None
    execution_state: ExecutionState
    previous_state: ExecutionState | None = None
    attempt_number: int = 0
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    runtime_profile_id: uuid.UUID | None = None
    failure_category: FailureCategory | None = None
    fallback_reason: FallbackReason | None = None
    idempotency_key_hash: str | None = None
    prompt_hash: str | None = None
    latency_ms: int | None = None
    answer_generated: bool = False
    metadata: JsonMapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.attempt_number < 0:
            raise ValueError("attempt_number cannot be negative")
        forbidden = {"prompt", "rendered_prompt", "secret", "credential", "token", "api_key"}
        keys = {str(key).lower() for key in self.metadata}
        if keys & forbidden:
            raise ValueError("audit metadata contains forbidden sensitive fields")


@runtime_checkable
class RuntimeAuditSink(Protocol):
    def emit(self, event: RuntimeAuditEvent) -> None: ...


class InMemoryRuntimeAuditSink:
    def __init__(self) -> None:
        self._events: list[RuntimeAuditEvent] = []

    def emit(self, event: RuntimeAuditEvent) -> None:
        self._events.append(event)

    def events(self) -> tuple[RuntimeAuditEvent, ...]:
        return tuple(self._events)


def hash_audit_value(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_runtime_audit_event(
    *,
    action: RuntimeAuditAction,
    request_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    execution_state: ExecutionState,
    previous_state: ExecutionState | None = None,
    attempt_number: int = 0,
    provider_id: uuid.UUID | None = None,
    model_id: uuid.UUID | None = None,
    runtime_profile_id: uuid.UUID | None = None,
    failure_category: FailureCategory | None = None,
    fallback_reason: FallbackReason | None = None,
    idempotency_key: str | None = None,
    rendered_prompt: str | None = None,
    latency_ms: int | None = None,
    answer_generated: bool = False,
    metadata: JsonMapping | None = None,
) -> RuntimeAuditEvent:
    return RuntimeAuditEvent(
        event_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        action=action,
        request_id=request_id,
        organization_id=organization_id,
        execution_state=execution_state,
        previous_state=previous_state,
        attempt_number=attempt_number,
        provider_id=provider_id,
        model_id=model_id,
        runtime_profile_id=runtime_profile_id,
        failure_category=failure_category,
        fallback_reason=fallback_reason,
        idempotency_key_hash=hash_audit_value(idempotency_key),
        prompt_hash=hash_audit_value(rendered_prompt),
        latency_ms=latency_ms,
        answer_generated=answer_generated,
        metadata=dict(metadata or {}),
    )
