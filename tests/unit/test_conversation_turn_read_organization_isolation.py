from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.conversation_runtime import read_conversation_turn


class _ScalarSession:
    def __init__(self, result):
        self.result = result
        self.statement = None
        self.calls = 0

    def scalar(self, statement):
        self.statement = statement
        self.calls += 1
        return self.result


def _turn(*, turn_id: uuid.UUID, organization_id: uuid.UUID):
    return SimpleNamespace(
        conversation_turn_id=turn_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
        conversation_id=uuid.uuid4(),
        assistant_id=None,
        assistant_session_id=None,
        assistant_run_id=None,
        assistant_response_id=None,
        turn_index=0,
        turn_role="user",
        turn_status="recorded",
        input_text="hello",
        output_text=None,
        response_format="markdown",
        citation_summary={},
        ordered_citations=[],
        turn_metadata={},
        created_at=None,
        updated_at=None,
    )


def test_read_conversation_turn_requires_organization_scope_in_persisted_query():
    turn_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    db = _ScalarSession(_turn(turn_id=turn_id, organization_id=organization_id))

    result = read_conversation_turn(
        db,
        str(turn_id),
        organization_id=organization_id,
    )

    assert result is not None
    assert result["conversation_turn_id"] == str(turn_id)
    assert result["organization_id"] == str(organization_id)
    assert db.calls == 1
    statement = str(db.statement)
    assert "conversation_turn_id" in statement
    assert "organization_id" in statement
    assert "ownership_scope" in statement


def test_read_conversation_turn_returns_none_when_scoped_lookup_has_no_match():
    db = _ScalarSession(None)

    result = read_conversation_turn(
        db,
        str(uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    assert result is None
    assert db.calls == 1


def test_read_conversation_turn_invalid_uuid_does_not_query_database():
    db = _ScalarSession(None)

    result = read_conversation_turn(
        db,
        "not-a-uuid",
        organization_id=uuid.uuid4(),
    )

    assert result is None
    assert db.calls == 0
