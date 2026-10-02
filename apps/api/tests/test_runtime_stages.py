from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.runtime_stages import (
    InvalidRuntimeStageError,
    InvalidRuntimeStageTransitionError,
    RuntimeStageName,
    RuntimeStageReporter,
)


def _execution() -> RuntimeExecution:
    now = datetime.now(UTC)
    return RuntimeExecution(
        id=uuid4(),
        organization_id=uuid4(),
        execution_type="generic.operation",
        subject_type="generic.subject",
        subject_id=uuid4(),
        status="running",
        requested_at=now,
        available_at=now,
        started_at=now,
        input_payload={},
        policy_snapshot={},
        metrics={},
    )


def _attempt(execution: RuntimeExecution) -> RuntimeExecutionAttempt:
    now = datetime.now(UTC)
    return RuntimeExecutionAttempt(
        id=uuid4(),
        organization_id=execution.organization_id,
        execution_id=execution.id,
        attempt_number=1,
        status="running",
        worker_id="worker-1",
        lease_token=uuid4(),
        leased_at=now,
        lease_expires_at=now + timedelta(minutes=5),
        heartbeat_at=now,
        started_at=now,
        provider_reference={},
        metrics={},
    )


def _reporter(existing_stage_events=None):
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    session.begin_nested.return_value = nullcontext()
    session.execute.return_value.all.return_value = list(existing_stage_events or [])

    reporter = RuntimeStageReporter(session)
    reporter.executions = MagicMock()
    reporter.events = MagicMock()
    reporter.events.append.side_effect = lambda event: event
    return reporter


def test_canonical_stage_vocabulary_is_stable() -> None:
    assert [stage.value for stage in RuntimeStageName] == [
        "source.acquire",
        "source.validate",
        "adapter.resolve",
        "content.extract",
        "content.normalize",
        "content.chunk",
        "content.quality_filter",
        "content.persist",
        "lexical.index",
        "artifact.publish",
        "execution.finalize",
    ]


def test_start_appends_bounded_stage_event_without_committing() -> None:
    execution = _execution()
    attempt = _attempt(execution)
    reporter = _reporter()
    reporter.executions.get.return_value = execution
    reporter.session.scalar.side_effect = [attempt.id, 4]
    now = datetime.now(UTC)
    stage_run_id = uuid4()

    event = reporter.start(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        attempt_id=attempt.id,
        stage_name=RuntimeStageName.SOURCE_ACQUIRE,
        stage_sequence=1,
        stage_run_id=stage_run_id,
        actor_reference="worker-1",
        metrics={"source_bytes": 1024, "cached": False},
        occurred_at=now,
    )

    assert event.event_type == "stage.started"
    assert event.sequence_number == 5
    assert event.attempt_id == attempt.id
    assert event.payload == {
        "stage_name": "source.acquire",
        "stage_sequence": 1,
        "stage_run_id": str(stage_run_id),
        "outcome": "started",
        "metrics": {"source_bytes": 1024, "cached": False},
        "started_at": now.isoformat(),
    }
    reporter.session.commit.assert_not_called()
    reporter.session.rollback.assert_not_called()


def test_complete_requires_matching_started_stage_and_records_duration() -> None:
    execution = _execution()
    attempt = _attempt(execution)
    stage_run_id = uuid4()
    reporter = _reporter(existing_stage_events=[("stage.started", {"stage_run_id": str(stage_run_id)})])
    reporter.executions.get.return_value = execution
    reporter.session.scalar.side_effect = [attempt.id, 8]
    started_at = datetime.now(UTC)
    finished_at = started_at + timedelta(milliseconds=1250)

    event = reporter.complete(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        attempt_id=attempt.id,
        stage_name="content.persist",
        stage_sequence=8,
        stage_run_id=stage_run_id,
        actor_reference="worker-1",
        started_at=started_at,
        metrics={"inserted_units": 3},
        occurred_at=finished_at,
    )

    assert event.event_type == "stage.completed"
    assert event.payload["outcome"] == "completed"
    assert event.payload["duration_ms"] == 1250
    assert event.payload["started_at"] == started_at.isoformat()
    assert event.payload["finished_at"] == finished_at.isoformat()


def test_terminal_stage_event_without_start_is_rejected() -> None:
    execution = _execution()
    attempt = _attempt(execution)
    reporter = _reporter()
    reporter.executions.get.return_value = execution
    reporter.session.scalar.return_value = attempt.id

    with pytest.raises(InvalidRuntimeStageTransitionError):
        reporter.complete(
            organization_id=execution.organization_id,
            execution_id=execution.id,
            attempt_id=attempt.id,
            stage_name="content.persist",
            stage_sequence=8,
            stage_run_id=uuid4(),
            actor_reference="worker-1",
            started_at=datetime.now(UTC),
        )

    reporter.events.append.assert_not_called()


def test_second_terminal_outcome_for_same_stage_run_is_rejected() -> None:
    execution = _execution()
    attempt = _attempt(execution)
    stage_run_id = uuid4()
    reporter = _reporter(
        existing_stage_events=[
            ("stage.started", {"stage_run_id": str(stage_run_id)}),
            ("stage.completed", {"stage_run_id": str(stage_run_id)}),
        ]
    )
    reporter.executions.get.return_value = execution
    reporter.session.scalar.return_value = attempt.id

    with pytest.raises(InvalidRuntimeStageTransitionError):
        reporter.fail(
            organization_id=execution.organization_id,
            execution_id=execution.id,
            attempt_id=attempt.id,
            stage_name="content.extract",
            stage_sequence=4,
            stage_run_id=stage_run_id,
            actor_reference="worker-1",
            started_at=datetime.now(UTC),
            error_code="extract_failed",
        )


def test_noncanonical_stage_is_rejected() -> None:
    reporter = _reporter()

    with pytest.raises(InvalidRuntimeStageError):
        reporter.start(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_id=uuid4(),
            stage_name="customer.special_stage",
            stage_sequence=1,
            actor_reference="worker-1",
        )


def test_stage_metrics_reject_nested_or_unbounded_values() -> None:
    reporter = _reporter()

    with pytest.raises(InvalidRuntimeStageError):
        reporter.start(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_id=uuid4(),
            stage_name="source.acquire",
            stage_sequence=1,
            actor_reference="worker-1",
            metrics={"document_content": {"text": "not allowed"}},
        )

    with pytest.raises(InvalidRuntimeStageError):
        reporter.start(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_id=uuid4(),
            stage_name="source.acquire",
            stage_sequence=1,
            actor_reference="worker-1",
            metrics={"diagnostic": "x" * 257},
        )


def test_failed_stage_requires_bounded_error_code() -> None:
    reporter = _reporter()

    with pytest.raises(InvalidRuntimeStageError):
        reporter.fail(
            organization_id=uuid4(),
            execution_id=uuid4(),
            attempt_id=uuid4(),
            stage_name="content.extract",
            stage_sequence=4,
            stage_run_id=uuid4(),
            actor_reference="worker-1",
            started_at=datetime.now(UTC),
            error_code="",
        )
