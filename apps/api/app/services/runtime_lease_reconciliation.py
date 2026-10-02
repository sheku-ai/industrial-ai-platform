from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.runtime_lifecycle import RuntimeLifecycleService


@dataclass(frozen=True)
class RuntimeLeaseReconciliationResult:
    execution_id: str
    attempt_id: str
    outcome: str
    attempt_number: int


class RuntimeLeaseReconciliationService:
    """Reconciles expired active execution leases without workload coupling."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        default_max_attempts: int = 3,
        default_retry_delay_seconds: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("session_factory is required")
        if default_max_attempts <= 0:
            raise ValueError("default_max_attempts must be positive")
        if default_retry_delay_seconds < 0:
            raise ValueError("default_retry_delay_seconds cannot be negative")
        self._session_factory = session_factory
        self._default_max_attempts = default_max_attempts
        self._default_retry_delay_seconds = default_retry_delay_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def reconcile(self, *, batch_limit: int = 100) -> list[RuntimeLeaseReconciliationResult]:
        if batch_limit <= 0:
            raise ValueError("batch_limit must be positive")

        now = self._clock()
        results: list[RuntimeLeaseReconciliationResult] = []
        with self._session_factory() as session:
            attempts = list(
                session.scalars(
                    select(RuntimeExecutionAttempt)
                    .where(
                        RuntimeExecutionAttempt.status.in_(["leased", "running"]),
                        RuntimeExecutionAttempt.lease_expires_at.is_not(None),
                        RuntimeExecutionAttempt.lease_expires_at <= now,
                    )
                    .order_by(RuntimeExecutionAttempt.lease_expires_at.asc())
                    .limit(batch_limit)
                    .with_for_update(skip_locked=True)
                ).all()
            )

            lifecycle = RuntimeLifecycleService(session)
            for attempt in attempts:
                execution = session.scalar(
                    select(RuntimeExecution)
                    .where(
                        RuntimeExecution.organization_id == attempt.organization_id,
                        RuntimeExecution.id == attempt.execution_id,
                    )
                    .with_for_update()
                )
                if execution is None or execution.status not in {"leased", "running"}:
                    continue

                policy = self._retry_policy(execution.policy_snapshot)
                lifecycle.expire(
                    execution.organization_id,
                    execution.id,
                    now=now,
                    reason="lease_expired",
                )
                attempt.error_message = "execution lease expired"
                attempt.metrics = {
                    **dict(attempt.metrics or {}),
                    "lease_reconciled": True,
                    "lease_reconciled_at": now.isoformat(),
                }

                if not isinstance(execution.input_payload, dict):
                    lifecycle.dead_letter(
                        execution.organization_id,
                        execution.id,
                        reason_code="invalid_execution_payload",
                        reason_message="execution input payload must be a JSON object",
                        now=now,
                    )
                    outcome = "dead_lettered_invalid_payload"
                elif attempt.attempt_number >= policy["max_attempts"]:
                    lifecycle.dead_letter(
                        execution.organization_id,
                        execution.id,
                        reason_code="lease_retry_exhausted",
                        reason_message="execution lease retry policy exhausted",
                        now=now,
                    )
                    outcome = "dead_lettered_retry_exhausted"
                else:
                    available_at = now + timedelta(seconds=policy["retry_delay_seconds"])
                    lifecycle.retry(
                        execution.organization_id,
                        execution.id,
                        available_at=available_at,
                    )
                    outcome = "retry_scheduled"

                execution.metrics = {
                    **dict(execution.metrics or {}),
                    "lease_reconciliation": {
                        "outcome": outcome,
                        "attempt_number": attempt.attempt_number,
                        "reconciled_at": now.isoformat(),
                    },
                }
                results.append(
                    RuntimeLeaseReconciliationResult(
                        execution_id=str(execution.id),
                        attempt_id=str(attempt.id),
                        outcome=outcome,
                        attempt_number=attempt.attempt_number,
                    )
                )

            session.commit()
        return results

    def _retry_policy(self, snapshot: dict[str, Any] | None) -> dict[str, int]:
        retry = snapshot.get("retry", {}) if isinstance(snapshot, dict) else {}
        if not isinstance(retry, dict):
            retry = {}
        max_attempts = retry.get("max_attempts", self._default_max_attempts)
        delay = retry.get("delay_seconds", self._default_retry_delay_seconds)
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts <= 0:
            max_attempts = self._default_max_attempts
        if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
            delay = self._default_retry_delay_seconds
        return {"max_attempts": max_attempts, "retry_delay_seconds": delay}
