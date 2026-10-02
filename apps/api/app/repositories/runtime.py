from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.runtime import (
    RuntimeExecution,
    RuntimeExecutionArtifact,
    RuntimeExecutionAttempt,
    RuntimeExecutionEvent,
    RuntimePersistenceRecord,
)


class RuntimeExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, execution: RuntimeExecution) -> RuntimeExecution:
        self.session.add(execution)
        self.session.flush()
        return execution

    def get(self, organization_id: UUID, execution_id: UUID, *, for_update: bool = False) -> RuntimeExecution | None:
        statement = select(RuntimeExecution).where(
            RuntimeExecution.organization_id == organization_id,
            RuntimeExecution.id == execution_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_by_idempotency_key(
        self,
        organization_id: UUID,
        execution_type: str,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> RuntimeExecution | None:
        statement = select(RuntimeExecution).where(
            RuntimeExecution.organization_id == organization_id,
            RuntimeExecution.execution_type == execution_type,
            RuntimeExecution.idempotency_key == idempotency_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list(
        self,
        organization_id: UUID,
        *,
        statuses: Sequence[str] | None = None,
        execution_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RuntimeExecution]:
        statement: Select[tuple[RuntimeExecution]] = select(RuntimeExecution).where(
            RuntimeExecution.organization_id == organization_id
        )
        if statuses:
            statement = statement.where(RuntimeExecution.status.in_(tuple(statuses)))
        if execution_type is not None:
            statement = statement.where(RuntimeExecution.execution_type == execution_type)
        statement = statement.order_by(RuntimeExecution.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())


class RuntimeAttemptRepository:
    ACTIVE_STATUSES = ("leased", "running")

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, attempt: RuntimeExecutionAttempt) -> RuntimeExecutionAttempt:
        self.session.add(attempt)
        self.session.flush()
        return attempt

    def get(
        self,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
    ) -> RuntimeExecutionAttempt | None:
        statement = select(RuntimeExecutionAttempt).where(
            RuntimeExecutionAttempt.organization_id == organization_id,
            RuntimeExecutionAttempt.execution_id == execution_id,
            RuntimeExecutionAttempt.id == attempt_id,
        )
        return self.session.scalar(statement)

    def get_active_for_update(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> RuntimeExecutionAttempt | None:
        statement = (
            select(RuntimeExecutionAttempt)
            .where(
                RuntimeExecutionAttempt.organization_id == organization_id,
                RuntimeExecutionAttempt.execution_id == execution_id,
                RuntimeExecutionAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .with_for_update()
        )
        return self.session.scalar(statement)

    def list(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RuntimeExecutionAttempt]:
        statement = (
            select(RuntimeExecutionAttempt)
            .where(
                RuntimeExecutionAttempt.organization_id == organization_id,
                RuntimeExecutionAttempt.execution_id == execution_id,
            )
            .order_by(RuntimeExecutionAttempt.attempt_number.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement).all())


class RuntimeEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: RuntimeExecutionEvent) -> RuntimeExecutionEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def list(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> list[RuntimeExecutionEvent]:
        statement = select(RuntimeExecutionEvent).where(
            RuntimeExecutionEvent.organization_id == organization_id,
            RuntimeExecutionEvent.execution_id == execution_id,
        )
        if after_sequence is not None:
            statement = statement.where(RuntimeExecutionEvent.sequence_number > after_sequence)
        statement = statement.order_by(RuntimeExecutionEvent.sequence_number.asc()).limit(limit)
        return list(self.session.scalars(statement).all())


class RuntimeArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, artifact: RuntimeExecutionArtifact) -> RuntimeExecutionArtifact:
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get(
        self,
        organization_id: UUID,
        execution_id: UUID,
        artifact_id: UUID,
        *,
        for_update: bool = False,
    ) -> RuntimeExecutionArtifact | None:
        statement = select(RuntimeExecutionArtifact).where(
            RuntimeExecutionArtifact.organization_id == organization_id,
            RuntimeExecutionArtifact.execution_id == execution_id,
            RuntimeExecutionArtifact.id == artifact_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list(
        self,
        organization_id: UUID,
        execution_id: UUID,
        *,
        artifact_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RuntimeExecutionArtifact]:
        statement = select(RuntimeExecutionArtifact).where(
            RuntimeExecutionArtifact.organization_id == organization_id,
            RuntimeExecutionArtifact.execution_id == execution_id,
        )
        if artifact_type is not None:
            statement = statement.where(RuntimeExecutionArtifact.artifact_type == artifact_type)
        statement = statement.order_by(RuntimeExecutionArtifact.created_at.asc()).limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())


class RuntimePersistenceRecordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, record: RuntimePersistenceRecord) -> RuntimePersistenceRecord:
        existing = self.get_by_identity(
            execution_id=record.execution_id,
            runtime_domain=record.runtime_domain,
            record_type=record.record_type,
            record_key=record.record_key,
        )
        if existing is not None:
            existing.artifact_id = record.artifact_id
            existing.processing_session_id = record.processing_session_id
            existing.correlation_id = record.correlation_id
            existing.provider = record.provider
            existing.execution_status = record.execution_status
            existing.content_hash = record.content_hash
            existing.summary = record.summary
            existing.payload = record.payload
            existing.validation = record.validation
            existing.metrics = record.metrics
            existing.persistence_status = record.persistence_status
            existing.occurred_at = record.occurred_at
            self.session.add(existing)
            self.session.flush()
            return existing
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_identity(
        self,
        *,
        execution_id: str,
        runtime_domain: str,
        record_type: str,
        record_key: str,
    ) -> RuntimePersistenceRecord | None:
        statement = select(RuntimePersistenceRecord).where(
            RuntimePersistenceRecord.execution_id == execution_id,
            RuntimePersistenceRecord.runtime_domain == runtime_domain,
            RuntimePersistenceRecord.record_type == record_type,
            RuntimePersistenceRecord.record_key == record_key,
        )
        return self.session.scalar(statement)

    def list_by_execution(self, execution_id: str) -> list[RuntimePersistenceRecord]:
        statement = (
            select(RuntimePersistenceRecord)
            .where(RuntimePersistenceRecord.execution_id == execution_id)
            .order_by(
                RuntimePersistenceRecord.runtime_domain.asc(),
                RuntimePersistenceRecord.record_type.asc(),
                RuntimePersistenceRecord.record_key.asc(),
            )
        )
        return list(self.session.scalars(statement).all())
