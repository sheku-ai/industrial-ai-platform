from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.runtime_lifecycle import RuntimeLifecycleService


class ContinuableRuntimeLifecycleService(RuntimeLifecycleService):
    def claim_selected(
        self, *, organization_id, execution_id, worker_id, lease_duration: timedelta, now: datetime | None = None
    ):
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self.session.scalar(
                select(RuntimeExecution)
                .where(
                    RuntimeExecution.organization_id == organization_id,
                    RuntimeExecution.id == execution_id,
                )
                .with_for_update(skip_locked=True)
            )
            if execution is None:
                return None

            if execution.status in {"leased", "running"}:
                active_attempt = self.attempts.get_active_for_update(organization_id, execution.id)
                if active_attempt is None:
                    return None
                if active_attempt.lease_expires_at is None or active_attempt.lease_expires_at <= current_time:
                    active_attempt.status = "expired"
                    active_attempt.finished_at = current_time
                    active_attempt.error_code = "lease_expired"
                    execution.status = "expired"
                    execution.error_code = "lease_expired"
                    execution.error_message = "execution lease expired"
                    self._append_event(
                        execution,
                        "execution.expired",
                        actor_type="system",
                        attempt_id=active_attempt.id,
                        payload={"reason": "lease_expired"},
                        occurred_at=current_time,
                    )
                elif active_attempt.worker_id == worker_id:
                    return execution, active_attempt
                else:
                    return None

            if execution.status not in {"pending", "scheduled", "expired"} or execution.available_at > current_time:
                return None

            attempt = RuntimeExecutionAttempt(
                organization_id=organization_id,
                execution_id=execution.id,
                attempt_number=self._next_attempt_number(organization_id, execution.id),
                status="leased",
                worker_id=worker_id,
                lease_token=uuid4(),
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

    def continue_later(
        self,
        organization_id,
        execution_id,
        *,
        lease_token,
        metrics=None,
        available_at: datetime | None = None,
        now: datetime | None = None,
    ):
        current_time = now or self._utcnow()
        with self._atomic():
            execution = self._execution_for_update(organization_id, execution_id)
            attempt = self._current_lease(execution, lease_token, current_time)
            attempt.status = "succeeded"
            attempt.finished_at = current_time
            attempt.metrics = metrics or attempt.metrics
            execution.status = "scheduled"
            execution.available_at = available_at or current_time
            execution.finished_at = None
            execution.metrics = metrics or execution.metrics
            execution.error_code = None
            execution.error_message = None
            self._append_event(
                execution,
                "execution.continued",
                actor_type="worker",
                actor_reference=attempt.worker_id,
                attempt_id=attempt.id,
                payload={"available_at": execution.available_at.isoformat()},
                occurred_at=current_time,
            )
            self.session.flush()
            return execution
