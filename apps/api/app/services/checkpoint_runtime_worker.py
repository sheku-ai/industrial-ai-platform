import logging
from datetime import timedelta

from sqlalchemy import select

from app.models.runtime import RuntimeExecution
from app.services.runtime_cancellation import RuntimeCancellationRequested
from app.services.runtime_continuation import ContinuableRuntimeLifecycleService
from app.services.runtime_lease import RuntimeLeaseLost
from app.services.runtime_lifecycle import InvalidLeaseError, RuntimeLifecycleService
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeWorkItem
from app.services.workspace_cleanup import WorkspaceTerminalOutcome

logger = logging.getLogger(__name__)


class SessionRuntimeHeartbeat:
    def __init__(self, session_factory, organization_id, execution_id, lease_token, extend_by):
        self._session_factory = session_factory
        self._organization_id = organization_id
        self._execution_id = execution_id
        self._lease_token = lease_token
        self._extend_by = extend_by

    def pulse(self):
        session = self._session_factory()
        try:
            result = RuntimeLifecycleService(session).heartbeat(
                self._organization_id,
                self._execution_id,
                lease_token=self._lease_token,
                extend_by=self._extend_by,
            )
            session.commit()
            return result
        except InvalidLeaseError as exc:
            session.rollback()
            raise RuntimeLeaseLost("runtime lease is no longer owned by this worker") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def is_cancellation_requested(self) -> bool:
        session = self._session_factory()
        try:
            requested_at = session.scalar(
                select(RuntimeExecution.cancel_requested_at).where(
                    RuntimeExecution.organization_id == self._organization_id,
                    RuntimeExecution.id == self._execution_id,
                )
            )
            return requested_at is not None
        finally:
            session.close()

    def raise_if_cancellation_requested(self) -> None:
        if self.is_cancellation_requested():
            raise RuntimeCancellationRequested("runtime cancellation was requested")

    def checkpoint(self):
        self.raise_if_cancellation_requested()
        return self.pulse()


class CheckpointRuntimeWorker:
    def __init__(
        self,
        session_factory,
        registry: RuntimeAdapterRegistry,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=5),
        heartbeat_extension: timedelta = timedelta(minutes=5),
        workspace_finalizer=None,
        heartbeat_factory=None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.worker_id = worker_id
        self.lease_duration = lease_duration
        self.heartbeat_extension = heartbeat_extension
        self.workspace_finalizer = workspace_finalizer
        self.heartbeat_factory = heartbeat_factory or SessionRuntimeHeartbeat

    def run_once(self, organization_id, *, execution_type=None, execution_id=None):
        item = self._claim(organization_id, execution_type, execution_id)
        if item is None:
            return None
        adapter = self.registry.resolve(item.execution_type)
        if adapter is None:
            self._fail(item, "adapter_not_configured", "no execution adapter is configured")
            self._finalize_workspace(item, WorkspaceTerminalOutcome.FAILED)
            return item
        self._start(item)
        heartbeat = self._build_heartbeat(item)
        outcome = None
        try:
            result = adapter.execute(item, heartbeat)
        except RuntimeCancellationRequested:
            self._cancel(item)
            outcome = WorkspaceTerminalOutcome.CANCELLED
        except RuntimeLeaseLost:
            outcome = WorkspaceTerminalOutcome.LEASE_LOST
        except Exception:
            logger.exception(
                "runtime adapter execution failed",
                extra={
                    "runtime_execution_id": str(item.execution_id),
                    "runtime_attempt_id": str(item.attempt_id),
                    "execution_type": item.execution_type,
                },
            )
            self._fail(item, "adapter_execution_failed", "execution adapter failed")
            outcome = WorkspaceTerminalOutcome.FAILED
        else:
            try:
                heartbeat.checkpoint()
            except RuntimeCancellationRequested:
                self._cancel(item)
                outcome = WorkspaceTerminalOutcome.CANCELLED
            except RuntimeLeaseLost:
                outcome = WorkspaceTerminalOutcome.LEASE_LOST
            else:
                metrics = dict(result.metrics)
                if result.continue_execution:
                    self._continue(item, metrics)
                else:
                    self._succeed(item, metrics)
                    outcome = WorkspaceTerminalOutcome.SUCCEEDED
        if outcome is not None:
            self._finalize_workspace(item, outcome)
        return item

    def _build_heartbeat(self, item):
        return self.heartbeat_factory(
            session_factory=self.session_factory,
            organization_id=item.organization_id,
            execution_id=item.execution_id,
            lease_token=item.lease_token,
            extend_by=self.heartbeat_extension,
        )

    def _finalize_workspace(self, item, outcome):
        if self.workspace_finalizer is None:
            return None
        return self.workspace_finalizer.finalize(item, outcome)

    def _claim(self, organization_id, execution_type, execution_id=None):
        session = self.session_factory()
        try:
            lifecycle = ContinuableRuntimeLifecycleService(session)
            if execution_id is None:
                claimed = lifecycle.claim(
                    organization_id=organization_id,
                    worker_id=self.worker_id,
                    lease_duration=self.lease_duration,
                    execution_type=execution_type,
                )
            else:
                claimed = lifecycle.claim_selected(
                    organization_id=organization_id,
                    execution_id=execution_id,
                    worker_id=self.worker_id,
                    lease_duration=self.lease_duration,
                )
            if claimed is None:
                session.commit()
                return None
            execution, attempt = claimed
            item = RuntimeWorkItem(
                organization_id=execution.organization_id,
                execution_id=execution.id,
                execution_type=execution.execution_type,
                subject_type=execution.subject_type,
                subject_id=execution.subject_id,
                attempt_id=attempt.id,
                attempt_number=attempt.attempt_number,
                lease_token=attempt.lease_token,
                input_payload=dict(execution.input_payload),
                policy_snapshot=dict(execution.policy_snapshot),
            )
            session.commit()
            return item
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _start(self, item):
        self._transition(item, "start")

    def _succeed(self, item, metrics):
        self._transition(item, "succeed", metrics=metrics)

    def _continue(self, item, metrics):
        session = self.session_factory()
        try:
            ContinuableRuntimeLifecycleService(session).continue_later(
                item.organization_id, item.execution_id, lease_token=item.lease_token, metrics=metrics
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _fail(self, item, error_code, error_message):
        self._transition(item, "fail", error_code=error_code, error_message=error_message)

    def _cancel(self, item):
        self._transition(item, "complete_cancel")

    def _transition(self, item, method_name, **kwargs):
        session = self.session_factory()
        try:
            lifecycle = RuntimeLifecycleService(session)
            getattr(lifecycle, method_name)(
                item.organization_id, item.execution_id, lease_token=item.lease_token, **kwargs
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
