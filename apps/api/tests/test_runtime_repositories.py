from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.models.runtime import (
    RuntimeExecution,
    RuntimeExecutionArtifact,
    RuntimeExecutionAttempt,
    RuntimeExecutionEvent,
)
from app.repositories.runtime import (
    RuntimeArtifactRepository,
    RuntimeAttemptRepository,
    RuntimeEventRepository,
    RuntimeExecutionRepository,
)


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_execution_get_is_tenant_scoped_and_does_not_commit() -> None:
    session = MagicMock()
    organization_id = uuid4()
    execution_id = uuid4()

    RuntimeExecutionRepository(session).get(organization_id, execution_id)

    statement = session.scalar.call_args.args[0]
    sql = _compiled(statement)
    assert "runtime.executions.organization_id" in sql
    assert str(organization_id) in sql
    assert "runtime.executions.id" in sql
    assert str(execution_id) in sql
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_execution_idempotency_lookup_is_scoped_by_tenant_and_type() -> None:
    session = MagicMock()
    organization_id = uuid4()

    RuntimeExecutionRepository(session).get_by_idempotency_key(
        organization_id,
        "document.ingestion",
        "request-001",
    )

    sql = _compiled(session.scalar.call_args.args[0])
    assert str(organization_id) in sql
    assert "document.ingestion" in sql
    assert "request-001" in sql


def test_attempt_lookup_requires_tenant_execution_and_attempt() -> None:
    session = MagicMock()
    organization_id = uuid4()
    execution_id = uuid4()
    attempt_id = uuid4()

    RuntimeAttemptRepository(session).get(organization_id, execution_id, attempt_id)

    sql = _compiled(session.scalar.call_args.args[0])
    assert str(organization_id) in sql
    assert str(execution_id) in sql
    assert str(attempt_id) in sql


def test_closed_attempts_have_no_general_update_repository_method() -> None:
    repository = RuntimeAttemptRepository(MagicMock())

    assert not hasattr(repository, "update")
    assert not hasattr(repository, "save")
    assert hasattr(repository, "get_active_for_update")


def test_event_repository_is_append_and_read_only() -> None:
    repository = RuntimeEventRepository(MagicMock())

    assert hasattr(repository, "append")
    assert hasattr(repository, "list")
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_event_list_is_tenant_and_execution_scoped() -> None:
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    organization_id = uuid4()
    execution_id = uuid4()

    RuntimeEventRepository(session).list(
        organization_id,
        execution_id,
        after_sequence=4,
    )

    sql = _compiled(session.scalars.call_args.args[0])
    assert str(organization_id) in sql
    assert str(execution_id) in sql
    assert "sequence_number > 4" in sql


def test_artifact_get_is_tenant_and_execution_scoped() -> None:
    session = MagicMock()
    organization_id = uuid4()
    execution_id = uuid4()
    artifact_id = uuid4()

    RuntimeArtifactRepository(session).get(
        organization_id,
        execution_id,
        artifact_id,
    )

    sql = _compiled(session.scalar.call_args.args[0])
    assert str(organization_id) in sql
    assert str(execution_id) in sql
    assert str(artifact_id) in sql


def test_add_operations_flush_but_never_commit() -> None:
    session = MagicMock()
    execution = MagicMock(spec=RuntimeExecution)
    attempt = MagicMock(spec=RuntimeExecutionAttempt)
    event = MagicMock(spec=RuntimeExecutionEvent)
    artifact = MagicMock(spec=RuntimeExecutionArtifact)

    RuntimeExecutionRepository(session).add(execution)
    RuntimeAttemptRepository(session).add(attempt)
    RuntimeEventRepository(session).append(event)
    RuntimeArtifactRepository(session).add(artifact)

    assert session.add.call_count == 4
    assert session.flush.call_count == 4
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
