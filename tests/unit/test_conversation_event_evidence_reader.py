from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationTurn
from app.services.conversation_event_evidence_reader import read_conversation_event_evidence_v1


def _turn(*, organization_id: uuid.UUID, conversation_turn_id: uuid.UUID | None = None) -> ConversationTurn:
    now = datetime.now(UTC)
    return ConversationTurn(
        conversation_turn_id=conversation_turn_id or uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
        conversation_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        assistant_session_id=uuid.uuid4(),
        assistant_run_id=uuid.uuid4(),
        assistant_response_id=uuid.uuid4(),
        request_id="request-1",
        turn_index=1,
        turn_role="assistant",
        turn_status="completed",
        input_text=None,
        output_text="Persisted answer",
        response_format="markdown",
        citation_summary={"verified": 1},
        ordered_citations=[{"citation_id": "citation-1"}],
        turn_metadata={"source": "runtime"},
        created_at=now,
        updated_at=now,
    )


def test_conversation_event_evidence_reader_reads_scoped_persisted_turn() -> None:
    organization_id = uuid.uuid4()
    turn = _turn(organization_id=organization_id)
    session = MagicMock(spec=Session)
    session.scalar.return_value = turn

    evidence = read_conversation_event_evidence_v1(
        session,
        organization_id=organization_id,
        conversation_turn_id=turn.conversation_turn_id,
    )

    assert evidence is not None
    assert evidence.conversation_turn_id == turn.conversation_turn_id
    assert evidence.organization_id == organization_id
    assert evidence.conversation_id == turn.conversation_id
    assert evidence.turn_role == "assistant"
    assert evidence.output_text == "Persisted answer"

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "ai.conversation_turns.conversation_turn_id" in compiled
    assert "ai.conversation_turns.organization_id" in compiled
    assert "ai.conversation_turns.ownership_scope" in compiled
    assert turn.conversation_turn_id.hex in compiled
    assert organization_id.hex in compiled
    assert "organization" in compiled


def test_conversation_event_evidence_reader_returns_none_when_not_found() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    evidence = read_conversation_event_evidence_v1(
        session,
        organization_id=uuid.uuid4(),
        conversation_turn_id=uuid.uuid4(),
    )

    assert evidence is None


def test_conversation_event_evidence_reader_rejects_mismatched_persisted_scope() -> None:
    requested_organization_id = uuid.uuid4()
    turn = _turn(organization_id=uuid.uuid4())
    session = MagicMock(spec=Session)
    session.scalar.return_value = turn

    with pytest.raises(ValueError, match="requested organization scope"):
        read_conversation_event_evidence_v1(
            session,
            organization_id=requested_organization_id,
            conversation_turn_id=turn.conversation_turn_id,
        )


def test_conversation_event_evidence_reader_rejects_legacy_scope() -> None:
    organization_id = uuid.uuid4()
    turn = _turn(organization_id=organization_id)
    turn.ownership_scope = "legacy_unscoped"
    session = MagicMock(spec=Session)
    session.scalar.return_value = turn

    with pytest.raises(ValueError, match="organization ownership scope"):
        read_conversation_event_evidence_v1(
            session,
            organization_id=organization_id,
            conversation_turn_id=turn.conversation_turn_id,
        )
