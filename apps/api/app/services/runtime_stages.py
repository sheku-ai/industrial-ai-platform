from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.runtime import RuntimeExecutionAttempt, RuntimeExecutionEvent
from app.repositories.runtime import RuntimeEventRepository, RuntimeExecutionRepository


class RuntimeStageError(RuntimeError):
    code = "runtime_stage_error"


class InvalidRuntimeStageError(RuntimeStageError):
    code = "invalid_runtime_stage"


class InvalidRuntimeStageTransitionError(RuntimeStageError):
    code = "invalid_runtime_stage_transition"


class RuntimeStageName(StrEnum):
    SOURCE_ACQUIRE = "source.acquire"
    SOURCE_VALIDATE = "source.validate"
    ADAPTER_RESOLVE = "adapter.resolve"
    CONTENT_EXTRACT = "content.extract"
    CONTENT_NORMALIZE = "content.normalize"
    CONTENT_CHUNK = "content.chunk"
    CONTENT_QUALITY_FILTER = "content.quality_filter"
    CONTENT_PERSIST = "content.persist"
    LEXICAL_INDEX = "lexical.index"
    ARTIFACT_PUBLISH = "artifact.publish"
    EXECUTION_FINALIZE = "execution.finalize"


class RuntimeStageOutcome(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


STAGE_EVENT_TYPES = {
    RuntimeStageOutcome.STARTED: "stage.started",
    RuntimeStageOutcome.COMPLETED: "stage.completed",
    RuntimeStageOutcome.SKIPPED: "stage.skipped",
    RuntimeStageOutcome.FAILED: "stage.failed",
}
TERMINAL_STAGE_OUTCOMES = {
    RuntimeStageOutcome.COMPLETED,
    RuntimeStageOutcome.SKIPPED,
    RuntimeStageOutcome.FAILED,
}
MAX_STAGE_METRICS = 32
MAX_STAGE_METRIC_KEY_LENGTH = 64
MAX_STAGE_STRING_LENGTH = 256
MAX_ERROR_CODE_LENGTH = 128


class RuntimeStageReporter:
    """Append bounded canonical stage events for one runtime attempt.

    The reporter does not commit or roll back. The caller owns transaction
    completion. Execution row locking serializes event sequence allocation and
    stage-cardinality checks for the execution.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.executions = RuntimeExecutionRepository(session)
        self.events = RuntimeEventRepository(session)

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        transaction = self.session.begin_nested() if self.session.in_transaction() else self.session.begin()
        with transaction:
            yield

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def start(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        stage_name: RuntimeStageName | str,
        stage_sequence: int,
        actor_reference: str,
        stage_run_id: UUID | None = None,
        metrics: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        return self._append(
            organization_id=organization_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            stage_name=stage_name,
            stage_sequence=stage_sequence,
            stage_run_id=stage_run_id or uuid4(),
            outcome=RuntimeStageOutcome.STARTED,
            actor_reference=actor_reference,
            metrics=metrics,
            occurred_at=occurred_at,
        )

    def complete(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        stage_name: RuntimeStageName | str,
        stage_sequence: int,
        stage_run_id: UUID,
        actor_reference: str,
        started_at: datetime,
        metrics: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        return self._append_terminal(
            organization_id=organization_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            stage_name=stage_name,
            stage_sequence=stage_sequence,
            stage_run_id=stage_run_id,
            outcome=RuntimeStageOutcome.COMPLETED,
            actor_reference=actor_reference,
            started_at=started_at,
            metrics=metrics,
            occurred_at=occurred_at,
        )

    def skip(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        stage_name: RuntimeStageName | str,
        stage_sequence: int,
        stage_run_id: UUID,
        actor_reference: str,
        started_at: datetime,
        metrics: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        return self._append_terminal(
            organization_id=organization_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            stage_name=stage_name,
            stage_sequence=stage_sequence,
            stage_run_id=stage_run_id,
            outcome=RuntimeStageOutcome.SKIPPED,
            actor_reference=actor_reference,
            started_at=started_at,
            metrics=metrics,
            occurred_at=occurred_at,
        )

    def fail(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        stage_name: RuntimeStageName | str,
        stage_sequence: int,
        stage_run_id: UUID,
        actor_reference: str,
        started_at: datetime,
        error_code: str,
        metrics: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        if not isinstance(error_code, str) or not error_code.strip():
            raise InvalidRuntimeStageError("error_code is required for a failed stage")
        if len(error_code.strip()) > MAX_ERROR_CODE_LENGTH:
            raise InvalidRuntimeStageError("error_code exceeds the bounded stage contract")
        return self._append_terminal(
            organization_id=organization_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            stage_name=stage_name,
            stage_sequence=stage_sequence,
            stage_run_id=stage_run_id,
            outcome=RuntimeStageOutcome.FAILED,
            actor_reference=actor_reference,
            started_at=started_at,
            metrics=metrics,
            error_code=error_code.strip(),
            occurred_at=occurred_at,
        )

    def _append_terminal(
        self, *, started_at: datetime, occurred_at: datetime | None = None, **kwargs
    ) -> RuntimeExecutionEvent:
        finished_at = occurred_at or self._utcnow()
        if started_at.tzinfo is None or finished_at.tzinfo is None:
            raise InvalidRuntimeStageError("stage timestamps must be timezone-aware")
        if finished_at < started_at:
            raise InvalidRuntimeStageError("stage finish cannot precede stage start")
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        return self._append(
            **kwargs,
            occurred_at=finished_at,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    def _append(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        stage_name: RuntimeStageName | str,
        stage_sequence: int,
        stage_run_id: UUID,
        outcome: RuntimeStageOutcome,
        actor_reference: str,
        metrics: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        started_at: datetime | None = None,
        duration_ms: int | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeExecutionEvent:
        canonical_name = self._canonical_stage_name(stage_name)
        if not isinstance(stage_sequence, int) or isinstance(stage_sequence, bool) or stage_sequence <= 0:
            raise InvalidRuntimeStageError("stage_sequence must be a positive integer")
        if not isinstance(actor_reference, str) or not actor_reference.strip():
            raise InvalidRuntimeStageError("actor_reference is required")
        bounded_metrics = self._bounded_metrics(metrics or {})
        event_time = occurred_at or self._utcnow()
        if event_time.tzinfo is None:
            raise InvalidRuntimeStageError("stage timestamp must be timezone-aware")

        with self._atomic():
            execution = self.executions.get(organization_id, execution_id, for_update=True)
            if execution is None:
                raise InvalidRuntimeStageError("runtime execution was not found")
            self._validate_attempt(organization_id, execution_id, attempt_id)
            self._validate_cardinality(execution_id, attempt_id, stage_run_id, outcome)

            payload: dict[str, Any] = {
                "stage_name": canonical_name.value,
                "stage_sequence": stage_sequence,
                "stage_run_id": str(stage_run_id),
                "outcome": outcome.value,
                "metrics": bounded_metrics,
            }
            if started_at is not None:
                payload["started_at"] = started_at.isoformat()
            if outcome == RuntimeStageOutcome.STARTED:
                payload["started_at"] = event_time.isoformat()
            else:
                payload["finished_at"] = event_time.isoformat()
                payload["duration_ms"] = duration_ms or 0
            if error_code is not None:
                payload["error_code"] = error_code

            event = RuntimeExecutionEvent(
                organization_id=organization_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                event_type=STAGE_EVENT_TYPES[outcome],
                sequence_number=self._next_event_sequence(organization_id, execution_id),
                occurred_at=event_time,
                actor_type="worker",
                actor_reference=actor_reference.strip(),
                payload=payload,
            )
            return self.events.append(event)

    def _validate_attempt(self, organization_id: UUID, execution_id: UUID, attempt_id: UUID) -> None:
        attempt = self.session.scalar(
            select(RuntimeExecutionAttempt.id).where(
                RuntimeExecutionAttempt.organization_id == organization_id,
                RuntimeExecutionAttempt.execution_id == execution_id,
                RuntimeExecutionAttempt.id == attempt_id,
            )
        )
        if attempt is None:
            raise InvalidRuntimeStageError("runtime attempt was not found")

    def _validate_cardinality(
        self,
        execution_id: UUID,
        attempt_id: UUID,
        stage_run_id: UUID,
        outcome: RuntimeStageOutcome,
    ) -> None:
        rows = list(
            self.session.execute(
                select(RuntimeExecutionEvent.event_type, RuntimeExecutionEvent.payload).where(
                    RuntimeExecutionEvent.execution_id == execution_id,
                    RuntimeExecutionEvent.attempt_id == attempt_id,
                    RuntimeExecutionEvent.event_type.in_(tuple(STAGE_EVENT_TYPES.values())),
                    RuntimeExecutionEvent.payload["stage_run_id"].astext == str(stage_run_id),
                )
            ).all()
        )
        event_types = {row[0] for row in rows}
        if outcome == RuntimeStageOutcome.STARTED:
            if "stage.started" in event_types:
                raise InvalidRuntimeStageTransitionError("stage run already started")
            if event_types.intersection({"stage.completed", "stage.skipped", "stage.failed"}):
                raise InvalidRuntimeStageTransitionError("terminal stage event already exists")
            return
        if "stage.started" not in event_types:
            raise InvalidRuntimeStageTransitionError("terminal stage event requires stage.started")
        if event_types.intersection({"stage.completed", "stage.skipped", "stage.failed"}):
            raise InvalidRuntimeStageTransitionError("stage run already has a terminal outcome")

    def _next_event_sequence(self, organization_id: UUID, execution_id: UUID) -> int:
        current = self.session.scalar(
            select(func.coalesce(func.max(RuntimeExecutionEvent.sequence_number), 0)).where(
                RuntimeExecutionEvent.organization_id == organization_id,
                RuntimeExecutionEvent.execution_id == execution_id,
            )
        )
        return int(current or 0) + 1

    @staticmethod
    def _canonical_stage_name(value: RuntimeStageName | str) -> RuntimeStageName:
        try:
            return value if isinstance(value, RuntimeStageName) else RuntimeStageName(str(value))
        except ValueError as exc:
            raise InvalidRuntimeStageError(f"unsupported canonical stage: {value}") from exc

    @staticmethod
    def _bounded_metrics(metrics: Mapping[str, Any]) -> dict[str, int | float | bool | str | None]:
        if not isinstance(metrics, Mapping):
            raise InvalidRuntimeStageError("stage metrics must be an object")
        if len(metrics) > MAX_STAGE_METRICS:
            raise InvalidRuntimeStageError("stage metrics exceed the bounded contract")

        bounded: dict[str, int | float | bool | str | None] = {}
        for raw_key, value in metrics.items():
            if not isinstance(raw_key, str) or not raw_key or len(raw_key) > MAX_STAGE_METRIC_KEY_LENGTH:
                raise InvalidRuntimeStageError("stage metric keys must be bounded non-empty strings")
            if value is None or isinstance(value, bool | int | float):
                bounded[raw_key] = value
                continue
            if isinstance(value, str) and len(value) <= MAX_STAGE_STRING_LENGTH:
                bounded[raw_key] = value
                continue
            raise InvalidRuntimeStageError(f"stage metric {raw_key} has an unsupported or unbounded value")
        return bounded
