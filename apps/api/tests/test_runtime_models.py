from sqlalchemy import ForeignKeyConstraint

from app.db.base import Base
from app.models.runtime import (
    RuntimeExecution,
    RuntimeExecutionArtifact,
    RuntimeExecutionAttempt,
    RuntimeExecutionEvent,
)


def test_runtime_tables_are_registered() -> None:
    assert {
        "runtime.executions",
        "runtime.execution_attempts",
        "runtime.execution_events",
        "runtime.execution_artifacts",
    }.issubset(Base.metadata.tables)


def test_runtime_models_use_runtime_schema() -> None:
    for model in (
        RuntimeExecution,
        RuntimeExecutionAttempt,
        RuntimeExecutionEvent,
        RuntimeExecutionArtifact,
    ):
        assert model.__table__.schema == "runtime"


def test_runtime_children_enforce_composite_tenant_ownership() -> None:
    attempts = RuntimeExecutionAttempt.__table__
    events = RuntimeExecutionEvent.__table__
    artifacts = RuntimeExecutionArtifact.__table__

    attempt_fks = {
        constraint.name for constraint in attempts.constraints if isinstance(constraint, ForeignKeyConstraint)
    }
    event_fks = {constraint.name for constraint in events.constraints if isinstance(constraint, ForeignKeyConstraint)}
    artifact_fks = {
        constraint.name for constraint in artifacts.constraints if isinstance(constraint, ForeignKeyConstraint)
    }

    assert "fk_runtime_execution_attempts_execution" in attempt_fks
    assert {
        "fk_runtime_execution_events_execution",
        "fk_runtime_execution_events_attempt",
    }.issubset(event_fks)
    assert {
        "fk_runtime_execution_artifacts_execution",
        "fk_runtime_execution_artifacts_attempt",
    }.issubset(artifact_fks)


def test_runtime_indexes_match_persistence_contract() -> None:
    execution_indexes = {index.name for index in RuntimeExecution.__table__.indexes}
    attempt_indexes = {index.name for index in RuntimeExecutionAttempt.__table__.indexes}
    event_indexes = {index.name for index in RuntimeExecutionEvent.__table__.indexes}
    artifact_indexes = {index.name for index in RuntimeExecutionArtifact.__table__.indexes}

    assert {
        "ix_runtime_executions_queue",
        "ix_runtime_executions_type_status",
        "ix_runtime_executions_subject",
        "ix_runtime_executions_correlation",
        "uq_runtime_executions_idempotency",
    }.issubset(execution_indexes)
    assert {
        "ix_runtime_execution_attempts_lease",
        "ix_runtime_execution_attempts_worker",
        "uq_runtime_execution_attempts_active",
    }.issubset(attempt_indexes)
    assert "ix_runtime_execution_events_timeline" in event_indexes
    assert "ix_runtime_execution_artifacts_type" in artifact_indexes


def test_runtime_json_metadata_column_avoids_declarative_reserved_name() -> None:
    assert RuntimeExecutionArtifact.metadata_.property.columns[0].name == "metadata"
