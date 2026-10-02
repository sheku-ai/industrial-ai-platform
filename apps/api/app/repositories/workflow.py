from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow_runtime import WorkflowDefinition, WorkflowRun, WorkflowStep


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_workflow(
        self,
        *,
        workflow_name: str,
        workflow_key: str,
        workflow_status: str = "prepared",
        workflow_version: str = "1.0",
        workflow_type: str = "platform_runtime",
        description: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> tuple[WorkflowDefinition, bool]:
        statement = select(WorkflowDefinition).where(
            WorkflowDefinition.workflow_key == workflow_key,
            WorkflowDefinition.workflow_version == workflow_version,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            existing.workflow_name = workflow_name
            existing.workflow_status = workflow_status
            existing.workflow_type = workflow_type
            existing.description = description
            existing.runtime_metadata = {**(existing.runtime_metadata or {}), **dict(runtime_metadata or {})}
            self.session.add(existing)
            self.session.flush()
            return existing, False
        record = WorkflowDefinition(
            workflow_name=workflow_name,
            workflow_key=workflow_key,
            workflow_status=workflow_status,
            workflow_version=workflow_version,
            workflow_type=workflow_type,
            description=description,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def get_workflow(self, workflow_id: uuid.UUID) -> WorkflowDefinition | None:
        return self.session.get(WorkflowDefinition, workflow_id)

    def list_workflows(self, *, workflow_status: str | None = None, limit: int = 100) -> list[WorkflowDefinition]:
        statement = select(WorkflowDefinition)
        if workflow_status:
            statement = statement.where(WorkflowDefinition.workflow_status == workflow_status)
        statement = statement.order_by(
            WorkflowDefinition.created_at.desc(), WorkflowDefinition.workflow_id.asc()
        ).limit(max(1, min(int(limit), 500)))
        return list(self.session.scalars(statement).all())

    def create_workflow_step(
        self,
        *,
        workflow_id: uuid.UUID,
        step_key: str,
        step_name: str,
        step_order: int,
        step_type: str,
        step_status: str = "prepared",
        runtime_domain: str,
        runtime_action: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> tuple[WorkflowStep, bool]:
        statement = select(WorkflowStep).where(
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.step_key == step_key,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            existing.step_name = step_name
            existing.step_order = int(step_order)
            existing.step_type = step_type
            existing.step_status = step_status
            existing.runtime_domain = runtime_domain
            existing.runtime_action = runtime_action
            existing.runtime_metadata = {**(existing.runtime_metadata or {}), **dict(runtime_metadata or {})}
            self.session.add(existing)
            self.session.flush()
            return existing, False
        record = WorkflowStep(
            workflow_id=workflow_id,
            step_key=step_key,
            step_name=step_name,
            step_order=int(step_order),
            step_type=step_type,
            step_status=step_status,
            runtime_domain=runtime_domain,
            runtime_action=runtime_action,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def list_workflow_steps(self, workflow_id: uuid.UUID) -> list[WorkflowStep]:
        statement = (
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_order.asc(), WorkflowStep.workflow_step_id.asc())
        )
        return list(self.session.scalars(statement).all())

    def create_workflow_run(
        self,
        *,
        workflow_id: uuid.UUID,
        run_status: str = "planned",
        execution_state: str = "metadata_only",
        requested_by: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        record = WorkflowRun(
            workflow_id=workflow_id,
            run_status=run_status,
            execution_state=execution_state,
            requested_by=requested_by,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_workflow_run(self, workflow_run_id: uuid.UUID) -> WorkflowRun | None:
        return self.session.get(WorkflowRun, workflow_run_id)

    def mark_workflow_run_completed(
        self,
        workflow_run_id: uuid.UUID,
        *,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun | None:
        record = self.get_workflow_run(workflow_run_id)
        if record is None:
            return None
        record.run_status = "completed"
        record.execution_state = "completed"
        record.completed_at = datetime.now(UTC)
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_workflow_run_failed(
        self,
        workflow_run_id: uuid.UUID,
        *,
        failure_reason: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun | None:
        record = self.get_workflow_run(workflow_run_id)
        if record is None:
            return None
        record.run_status = "failed"
        record.execution_state = "failed"
        record.failed_at = datetime.now(UTC)
        record.failure_reason = failure_reason
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_workflow_run_blocked(
        self,
        workflow_run_id: uuid.UUID,
        *,
        failure_reason: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun | None:
        record = self.get_workflow_run(workflow_run_id)
        if record is None:
            return None
        record.run_status = "blocked"
        record.execution_state = "blocked"
        record.failure_reason = failure_reason
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record
