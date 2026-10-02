from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.runtime_lifecycle import (
    InvalidLeaseError,
    InvalidRuntimeTransitionError,
    RuntimeLifecycleService,
)


def _service() -> RuntimeLifecycleService:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    session.begin_nested.return_value = nullcontext()
    session.scalar.return_value = 0
    service = RuntimeLifecycleService(session)
    service.executions = MagicMock()
    service.attempts = MagicMock()
    service.events = MagicMock()
    return service


def _execution(status: str = "pending") -> RuntimeExecution:
    now = datetime.now(UTC)
    return RuntimeExecution(
        id=uuid4(),
        organization_id=uuid4(),
        execution_type="generic.operation",
        subject_type="generic.subject",
        subject_id=uuid4(),
        idempotency_key="request-001",
        priority=100,
        status=status,
        requested_at=now,
        available_at=now,
        input_payload={},
        policy_snapshot={},
        metrics={},
    )


def _attempt(execution: RuntimeExecution, status: str = "leased") -> RuntimeExecutionAttempt:
    now = datetime.now(UTC)
    return RuntimeExecutionAttempt(
        id=uuid4(),
        organization_id=execution.organization_id,
        execution_id=execution.id,
        attempt_number=1,
        status=status,
        worker_id="worker-1",
        lease_token=uuid4(),
        leased_at=now,
        lease_expires_at=now + timedelta(minutes=5),
        heartbeat_at=now,
        provider_reference={},
        metrics={},
    )


def test_lifecycle_service_exposes_complete_sprint_contract() -> None:
    service = _service()

    for method in (
        "create_or_get",
        "schedule",
        "claim",
        "heartbeat",
        "start",
        "succeed",
        "fail",
        "expire",
        "retry",
        "request_cancel",
        "complete_cancel",
        "dead_letter",
    ):
        assert hasattr(service, method)


def test_schedule_updates_state_and_appends_event_atomically() -> None:
    service = _service()
    execution = _execution("pending")
    service.executions.get.return_value = execution
    available_at = execution.requested_at + timedelta(minutes=10)

    result = service.schedule(
        execution.organization_id,
        execution.id,
        available_at=available_at,
        actor_reference="operator-1",
    )

    assert result.status == "scheduled"
    assert result.available_at == available_at
    service.events.append.assert_called_once()
    service.session.commit.assert_not_called()
    service.session.rollback.assert_not_called()


def test_terminal_execution_cannot_be_scheduled() -> None:
    service = _service()
    execution = _execution("succeeded")
    service.executions.get.return_value = execution

    with pytest.raises(InvalidRuntimeTransitionError):
        service.schedule(
            execution.organization_id,
            execution.id,
            available_at=execution.requested_at + timedelta(minutes=1),
        )

    service.events.append.assert_not_called()


def test_start_requires_current_non_expired_lease() -> None:
    service = _service()
    execution = _execution("leased")
    attempt = _attempt(execution)
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt

    service.start(
        execution.organization_id,
        execution.id,
        lease_token=attempt.lease_token,
        now=attempt.leased_at + timedelta(seconds=1),
    )

    assert execution.status == "running"
    assert attempt.status == "running"
    assert execution.started_at is not None
    service.events.append.assert_called_once()


def test_stale_lease_token_is_rejected() -> None:
    service = _service()
    execution = _execution("leased")
    attempt = _attempt(execution)
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt

    with pytest.raises(InvalidLeaseError):
        service.start(
            execution.organization_id,
            execution.id,
            lease_token=uuid4(),
            now=attempt.leased_at + timedelta(seconds=1),
        )


def test_expired_lease_cannot_heartbeat() -> None:
    service = _service()
    execution = _execution("running")
    attempt = _attempt(execution, "running")
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt

    with pytest.raises(InvalidLeaseError):
        service.heartbeat(
            execution.organization_id,
            execution.id,
            lease_token=attempt.lease_token,
            extend_by=timedelta(minutes=5),
            now=attempt.lease_expires_at + timedelta(seconds=1),
        )


def test_success_closes_attempt_and_execution() -> None:
    service = _service()
    execution = _execution("running")
    attempt = _attempt(execution, "running")
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt
    now = attempt.leased_at + timedelta(minutes=1)

    result = service.succeed(
        execution.organization_id,
        execution.id,
        lease_token=attempt.lease_token,
        metrics={"records": 7},
        now=now,
    )

    assert result.status == "succeeded"
    assert result.finished_at == now
    assert result.error_code is None
    assert attempt.status == "succeeded"
    assert attempt.finished_at == now
    assert attempt.metrics == {"records": 7}
    service.events.append.assert_called_once()


def test_failed_execution_can_be_retried_without_reopening_old_attempt() -> None:
    service = _service()
    execution = _execution("failed")
    execution.finished_at = datetime.now(UTC)
    execution.error_code = "processing_failed"
    execution.error_message = "sanitized failure"
    service.executions.get.return_value = execution
    next_time = datetime.now(UTC) + timedelta(minutes=2)

    result = service.retry(
        execution.organization_id,
        execution.id,
        available_at=next_time,
        actor_reference="operator-1",
    )

    assert result.status == "scheduled"
    assert result.finished_at is None
    assert result.error_code is None
    assert result.error_message is None
    assert result.available_at == next_time
    service.attempts.get_active_for_update.assert_not_called()
    service.events.append.assert_called_once()


def test_active_cancellation_requires_current_lease_token() -> None:
    service = _service()
    execution = _execution("running")
    execution.cancel_requested_at = datetime.now(UTC)
    attempt = _attempt(execution, "running")
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt

    with pytest.raises(InvalidLeaseError):
        service.complete_cancel(
            execution.organization_id,
            execution.id,
            lease_token=None,
        )


def test_cancelled_execution_and_attempt_are_closed_together() -> None:
    service = _service()
    execution = _execution("running")
    execution.cancel_requested_at = datetime.now(UTC)
    attempt = _attempt(execution, "running")
    service.executions.get.return_value = execution
    service.attempts.get_active_for_update.return_value = attempt
    now = attempt.leased_at + timedelta(minutes=1)

    result = service.complete_cancel(
        execution.organization_id,
        execution.id,
        lease_token=attempt.lease_token,
        now=now,
    )

    assert result.status == "cancelled"
    assert result.finished_at == now
    assert attempt.status == "cancelled"
    assert attempt.finished_at == now
    service.events.append.assert_called_once()


def test_dead_letter_requires_failed_or_expired_execution() -> None:
    service = _service()
    execution = _execution("running")
    service.executions.get.return_value = execution

    with pytest.raises(InvalidRuntimeTransitionError):
        service.dead_letter(
            execution.organization_id,
            execution.id,
            reason_code="retry_exhausted",
            reason_message="retry budget exhausted",
        )
