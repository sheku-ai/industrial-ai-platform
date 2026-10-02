from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt, RuntimeExecutionEvent
from app.repositories.runtime import RuntimeAttemptRepository, RuntimeEventRepository, RuntimeExecutionRepository

TERMINAL_EXECUTION_STATUSES = {"succeeded", "failed", "cancelled", "dead_lettered"}
CLOSED_ATTEMPT_STATUSES = {"succeeded", "failed", "abandoned", "expired", "cancelled"}
ACTIVE_ATTEMPT_STATUSES = {"leased", "running"}


class RuntimeLifecycleError(RuntimeError):
    code = "runtime_lifecycle_error"


class RuntimeNotFoundError(RuntimeLifecycleError):
    code = "runtime_not_found"


class InvalidRuntimeTransitionError(RuntimeLifecycleError):
    code = "invalid_runtime_transition"


class InvalidLeaseError(RuntimeLifecycleError):
    code = "invalid_or_expired_lease"


class RuntimeLifecycleService:
    """Owns atomic runtime state transitions and their append-only events."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.executions = RuntimeExecutionRepository(session)
        self.attempts = RuntimeAttemptRepository(session)
        self.events = RuntimeEventRepository(session)

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        transaction = self.session.begin_nested() if self.session.in_transaction() else self.session.begin()
        with transaction:
            yield

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def _execution_for_update(self, organization_id: UUID, execution_id: UUID) -> RuntimeExecution:
        execution = self.executions.get(organization_id, execution_id, for_update=True)
        if execution is None:
            raise RuntimeNotFoundError("runtime execution was not found")
        return execution

    def _next_event_sequence(self, organization_id: UUID, execution_id: UUID) -> int:
        current = self.session.scalar(
            select(func.coalesce(func.max(RuntimeExecutionEvent.sequence_number), 0)).where(
                RuntimeExecutionEvent.organization_id == organization_id,
                RuntimeExecutionEvent.execution_id == execution_id,
            )
        )
        return int(current or 0) + 1

    def _next_attempt_number(self, organization_id: UUID, execution_id: UUID) -> int:
        current = self.session.scalar(
            select(func.coalesce(func.max(RuntimeExecutionAttempt.attempt_number), 0)).where(
                RuntimeExecutionAttempt.organization_id == organization_id,
                RuntimeExecutionAttempt.execution_id == execution_id,
            )
        )
        return int(current or 0) + 1

    def _append_event(
        self,
        execution: RuntimeExecution,
        event_type: str,
        *,
        actor_type: str,
        actor_reference: str | None = None,
        attempt_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        event = RuntimeExecutionEvent(
            organization_id=execution.organization_id,
            execution_id=execution.id,
            attempt_id=attempt_id,
            event_type=event_type,
            sequence_number=self._next_event_sequence(execution.organization_id, execution.id),
            occurred_at=occurred_at or self._utcnow(),
            actor_type=actor_type,
            actor_reference=actor_reference,
            payload=payload or {},
        )
        return self.events.append(event)

    def _current_lease(
        self,
        execution: RuntimeExecution,
        lease_token: UUID,
        now: datetime,
    ) -> RuntimeExecutionAttempt:
        attempt = self.attempts.get_active_for_update(execution.organization_id, execution.id)
        if (
            attempt is None
            or attempt.status not in ACTIVE_ATTEMPT_STATUSES
            or attempt.lease_token != lease_token
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at <= now
        ):
            raise InvalidLeaseError("the current non-expired lease token is required")
        return attempt

    def create_or_get(
        self,
        *,
        organization_id: UUID,
        execution_type: str,
        subject_type: str,
        subject_id: UUID,
        idempotency_key: str,
        requested_by: str | None = None,
        correlation_id: str | None = None,
        priority: int = 100,
        available_at: datetime | None = None,
        input_payload: dict[str, Any] | None = None,
        policy_snapshot: dict[str, Any] | None = None,
    ) -> tuple[RuntimeExecution, bool]:
        try:
            with self._atomic():
                existing = self.executions.get_by_idempotency_key(
                    organization_id,
                    execution_type,
                    idempotency_key,
                    for_update=True,
                )
                if existing is not None:
                    return existing, False

                now = self._utcnow()
                execution = RuntimeExecution(
                    organization_id=organization_id,
                    execution_type=execution_type,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    priority=priority,
                    status="pending",
                    requested_at=now,
                    available_at=available_at or now,
                    input_payload=input_payload or {},
                    policy_snapshot=policy_snapshot or {},
                    metrics={},
                    created_by=requested_by,
                    updated_by=requested_by,
                )
                self.executions.add(execution)
                self._append_event(
                    execution,
                    "execution.created",
                    actor_type="user" if requested_by else "system",
                    actor_reference=requested_by,
                    payload={"status": "pending"},
                    occurred_at=now,
                )
                return execution, True
        except IntegrityError:
            with self._atomic():
                existing = self.executions.get_by_idempotency_key(
                    organization_id,
                    execution_type,
                    idempotency_key,
                )
                if existing is None:
                    raise
                return existing, False

    def schedule(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        available_at: datetime,
        actor_reference: str | None = None,
    ) -> RuntimeExecution:
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.status not in {"pending", "scheduled"}:
                raise InvalidRuntimeTransitionError(f"cannot schedule execution from {execution.status}")
            if available_at < execution.requested_at:
                raise InvalidRuntimeTransitionError("available_at cannot precede requested_at")
            execution.status = "scheduled"
            execution.available_at = available_at
            execution.updated_by = actor_reference
            self._append_event(
                execution,
                "execution.scheduled",
                actor_type="user" if actor_reference else "system",
                actor_reference=actor_reference,
                payload={"available_at": available_at.isoformat()},
            )
            self.session.flush()
            return execution

    def claim(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        lease_duration: timedelta,
        execution_type: str | None = None,
        now: datetime | None = None,
    ) -> tuple[RuntimeExecution, RuntimeExecutionAttempt] | None:
        current_time = now or self._utcnow()
        with self._atomic():
            statement = select(RuntimeExecution).where(
                RuntimeExecution.organization_id == organization_id,
                RuntimeExecution.status.in_(("pending", "scheduled", "expired")),
                RuntimeExecution.available_at <= current_time,
            )
            if execution_type is not None:
                statement = statement.where(RuntimeExecution.execution_type == execution_type)
            statement = (
                statement.order_by(
                    RuntimeExecution.priority.asc(),
                    RuntimeExecution.available_at.asc(),
                    RuntimeExecution.created_at.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            execution = self.session.scalar(statement)
            if execution is None:
                return None
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                raise InvalidRuntimeTransitionError("terminal execution cannot be claimed")

            lease_token = uuid4()
            attempt = RuntimeExecutionAttempt(
                organization_id=organization_id,
                execution_id=execution.id,
                attempt_number=self._next_attempt_number(organization_id, execution.id),
                status="leased",
                worker_id=worker_id,
                lease_token=lease_token,
                leased_at=current_time,
                lease_expires_at=current_time + lease_duration,
                heartbeat_at=current_time,
                provider_reference={},
                metrics={},
            )
            self.attempts.add(attempt)
            execution.status = "leased"
            execution.error_code = None
            execution.error_message = None
            self._append_event(
                execution,
                "execution.leased",
                actor_type="worker",
                actor_reference=worker_id,
                attempt_id=attempt.id,
                payload={
                    "attempt_number": attempt.attempt_number,
                    "lease_expires_at": attempt.lease_expires_at.isoformat(),
                },
                occurred_at=current_time,
            )
            self.session.flush()
            return execution, attempt

    def heartbeat(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID,
        extend_by: timedelta,
        now: datetime | None = None,
    ) -> RuntimeExecutionAttempt:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            attempt = self._current_lease(execution, lease_token, current_time)
            attempt.heartbeat_at = current_time
            attempt.lease_expires_at = current_time + extend_by
            self._append_event(
                execution,
                "attempt.heartbeat",
                actor_type="worker",
                actor_reference=attempt.worker_id,
                attempt_id=attempt.id,
                payload={"lease_expires_at": attempt.lease_expires_at.isoformat()},
                occurred_at=current_time,
            )
            self.session.flush()
            return attempt

    def start(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            attempt = self._current_lease(execution, lease_token, current_time)
            if attempt.status != "leased" or execution.status != "leased":
                raise InvalidRuntimeTransitionError("only a leased execution can start")
            attempt.status = "running"
            attempt.started_at = current_time
            execution.status = "running"
            execution.started_at = execution.started_at or current_time
            self._append_event(
                execution,
                "execution.started",
                actor_type="worker",
                actor_reference=attempt.worker_id,
                attempt_id=attempt.id,
                occurred_at=current_time,
            )
            self.session.flush()
            return execution

    def succeed(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID,
        metrics: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        return self._complete(
            organization_id,
            execution_id,
            lease_token=lease_token,
            execution_status="succeeded",
            attempt_status="succeeded",
            event_type="execution.succeeded",
            metrics=metrics,
            now=now,
        )

    def fail(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID,
        error_code: str,
        error_message: str,
        metrics: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        return self._complete(
            organization_id,
            execution_id,
            lease_token=lease_token,
            execution_status="failed",
            attempt_status="failed",
            event_type="execution.failed",
            error_code=error_code,
            error_message=error_message,
            metrics=metrics,
            now=now,
        )

    def _complete(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID,
        execution_status: str,
        attempt_status: str,
        event_type: str,
        error_code: str | None = None,
        error_message: str | None = None,
        metrics: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                raise InvalidRuntimeTransitionError("terminal execution cannot be completed again")
            attempt = self._current_lease(execution, lease_token, current_time)
            if attempt.status not in ACTIVE_ATTEMPT_STATUSES:
                raise InvalidRuntimeTransitionError("closed attempt cannot be mutated")
            attempt.status = attempt_status
            attempt.finished_at = current_time
            attempt.metrics = metrics or attempt.metrics
            attempt.error_code = error_code
            attempt.error_message = error_message
            execution.status = execution_status
            execution.finished_at = current_time
            execution.metrics = metrics or execution.metrics
            execution.error_code = error_code
            execution.error_message = error_message
            self._append_event(
                execution,
                event_type,
                actor_type="worker",
                actor_reference=attempt.worker_id,
                attempt_id=attempt.id,
                payload={"error_code": error_code} if error_code else {},
                occurred_at=current_time,
            )
            self.session.flush()
            return execution

    def expire(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        now: datetime | None = None,
        reason: str = "lease_expired",
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            attempt = self.attempts.get_active_for_update(organization_id, execution_id)
            if attempt is None or attempt.lease_expires_at is None or attempt.lease_expires_at > current_time:
                raise InvalidRuntimeTransitionError("execution has no expired active lease")
            attempt.status = "expired"
            attempt.finished_at = current_time
            attempt.error_code = reason
            execution.status = "expired"
            execution.error_code = reason
            execution.error_message = "execution lease expired"
            self._append_event(
                execution,
                "execution.expired",
                actor_type="system",
                attempt_id=attempt.id,
                payload={"reason": reason},
                occurred_at=current_time,
            )
            self.session.flush()
            return execution

    def retry(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        available_at: datetime | None = None,
        actor_reference: str | None = None,
    ) -> RuntimeExecution:
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.status not in {"failed", "expired"}:
                raise InvalidRuntimeTransitionError(f"cannot retry execution from {execution.status}")
            execution.status = "scheduled"
            execution.available_at = available_at or self._utcnow()
            execution.finished_at = None
            execution.error_code = None
            execution.error_message = None
            execution.updated_by = actor_reference
            self._append_event(
                execution,
                "execution.retry_scheduled",
                actor_type="user" if actor_reference else "system",
                actor_reference=actor_reference,
                payload={"available_at": execution.available_at.isoformat()},
            )
            self.session.flush()
            return execution

    def request_cancel(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        actor_reference: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                raise InvalidRuntimeTransitionError("terminal execution cannot receive cancellation request")
            execution.cancel_requested_at = current_time
            execution.updated_by = actor_reference
            self._append_event(
                execution,
                "execution.cancel_requested",
                actor_type="user" if actor_reference else "system",
                actor_reference=actor_reference,
                occurred_at=current_time,
            )
            self.session.flush()
            return execution

    def complete_cancel(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        lease_token: UUID | None = None,
        actor_reference: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.cancel_requested_at is None:
                raise InvalidRuntimeTransitionError("cancellation was not requested")
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                raise InvalidRuntimeTransitionError("terminal execution cannot be cancelled again")
            attempt = self.attempts.get_active_for_update(organization_id, execution_id)
            if attempt is not None:
                if lease_token is None:
                    raise InvalidLeaseError("lease token is required to cancel active work")
                attempt = self._current_lease(execution, lease_token, current_time)
                attempt.status = "cancelled"
                attempt.finished_at = current_time
            execution.status = "cancelled"
            execution.finished_at = current_time
            execution.error_code = None
            execution.error_message = None
            self._append_event(
                execution,
                "execution.cancelled",
                actor_type="worker" if attempt is not None else "system",
                actor_reference=attempt.worker_id if attempt is not None else actor_reference,
                attempt_id=attempt.id if attempt is not None else None,
                occurred_at=current_time,
            )
            self.session.flush()
            return execution

    def dead_letter(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        reason_code: str,
        reason_message: str,
        actor_reference: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeExecution:
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            if execution.status not in {"failed", "expired"}:
                raise InvalidRuntimeTransitionError(f"cannot dead-letter execution from {execution.status}")
            execution.status = "dead_lettered"
            execution.finished_at = current_time
            execution.error_code = reason_code
            execution.error_message = reason_message
            execution.updated_by = actor_reference
            self._append_event(
                execution,
                "execution.dead_lettered",
                actor_type="user" if actor_reference else "system",
                actor_reference=actor_reference,
                payload={"reason_code": reason_code},
                occurred_at=current_time,
            )
            self.session.flush()
            return execution
