from __future__ import annotations

import inspect
import uuid

from sqlalchemy.dialects import postgresql

from app.services.conversation_runtime import (
    _lock_scoped_conversation_for_turn_write,
    attach_assistant_response_to_conversation_runtime,
    build_conversation_turn_runtime,
)


class _CapturingSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        return self.result


def test_turn_write_lock_is_scoped_and_uses_for_update() -> None:
    sentinel = object()
    session = _CapturingSession(sentinel)
    conversation_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    result = _lock_scoped_conversation_for_turn_write(  # type: ignore[arg-type]
        session,
        conversation_id=conversation_id,
        organization_id=organization_id,
    )

    assert result is sentinel
    assert session.statement is not None
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR UPDATE" in sql
    assert f"conversations.conversation_id = '{conversation_id}'" in sql
    assert f"conversations.organization_id = '{organization_id}'" in sql
    assert "conversations.ownership_scope = 'organization'" in sql


def test_conversation_turn_runtime_locks_before_allocating_turn_index() -> None:
    source = inspect.getsource(build_conversation_turn_runtime)

    lock_position = source.index("_lock_scoped_conversation_for_turn_write")
    allocation_position = source.index("get_next_conversation_turn_index")

    assert lock_position < allocation_position


def test_assistant_response_attachment_locks_before_turn_attachment() -> None:
    source = inspect.getsource(attach_assistant_response_to_conversation_runtime)

    lock_position = source.index("_lock_scoped_conversation_for_turn_write")
    attachment_position = source.index("attach_assistant_response_turn")

    assert lock_position < attachment_position
