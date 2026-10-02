from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import chat_runtime
from app.services.conversation_runtime import CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    original = Exception("integrity error")
    original.diag = SimpleNamespace(constraint_name=constraint_name)  # type: ignore[attr-defined]
    return IntegrityError("statement", {}, original)


class _Nested:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self):
        self.events.append("nested_enter")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.events.append("nested_rollback" if exc_type is not None else "nested_release")
        return False


class _Session:
    def __init__(self) -> None:
        self.events: list[str] = []

    def begin_nested(self):
        self.events.append("begin_nested")
        return _Nested(self.events)

    def add(self, record) -> None:
        self.events.append("add_turn")

    def flush(self) -> None:
        self.events.append("flush_request_id")

    def commit(self) -> None:
        self.events.append("commit")


@pytest.fixture(autouse=True)
def _persist_conversation_context(monkeypatch):
    def _resolve(session, **kwargs):
        session.events.append("create_context_package")
        return SimpleNamespace(conversation_context_package_id=uuid.uuid4())

    monkeypatch.setattr(chat_runtime, "resolve_conversation_context_package", _resolve)

    def _resolve_interaction(session, **kwargs):
        session.events.append("create_interaction_decision")
        return SimpleNamespace(interaction_decision_id=uuid.uuid4())

    monkeypatch.setattr(chat_runtime, "resolve_interaction_decision", _resolve_interaction)


class _Repository:
    fail_constraint: str | None = None
    winner_conversation = None

    def __init__(self, session: _Session) -> None:
        self.session = session

    def create_conversation(self, **kwargs):
        self.session.events.append("create_conversation")
        return SimpleNamespace(conversation_id=uuid.uuid4())

    def create_conversation_turn(self, **kwargs):
        self.session.events.append("create_user_turn")
        if self.fail_constraint is not None:
            raise _integrity_error(self.fail_constraint)
        return SimpleNamespace(
            conversation_turn_id=uuid.uuid4(),
            conversation_id=kwargs["conversation_id"],
            request_id=None,
        )

    def get_scoped_conversation(self, conversation_id, *, organization_id):
        self.session.events.append("read_winner_conversation")
        return self.winner_conversation


def _call(session: _Session):
    return chat_runtime._create_initial_idempotent_chat_turn(
        session,
        organization_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        request_id="request-atomicity-1",
        message="hello",
        requested_by="tester",
        data_origin="operational",
        context={},
        metadata={},
    )


def test_first_message_persists_conversation_and_user_turn_in_one_savepoint(monkeypatch) -> None:
    session = _Session()
    _Repository.fail_constraint = None
    monkeypatch.setattr(chat_runtime, "AssistantRepository", _Repository)

    conversation, turn, created = _call(session)

    assert created is True
    assert turn.conversation_id == conversation.conversation_id
    assert turn.request_id == "request-atomicity-1"
    assert session.events.index("nested_enter") < session.events.index("create_conversation")
    assert session.events.index("create_conversation") < session.events.index("create_user_turn")
    assert session.events.index("create_user_turn") < session.events.index("create_context_package")
    assert session.events.index("create_context_package") < session.events.index("create_interaction_decision")
    assert session.events.index("create_interaction_decision") < session.events.index("nested_release")
    assert session.events.index("nested_release") < session.events.index("commit")


def test_same_request_collision_reuses_winner_after_atomic_rollback(monkeypatch) -> None:
    session = _Session()
    winner_turn = SimpleNamespace(conversation_turn_id=uuid.uuid4(), conversation_id=uuid.uuid4())
    winner_conversation = SimpleNamespace(conversation_id=winner_turn.conversation_id)
    _Repository.fail_constraint = CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT
    _Repository.winner_conversation = winner_conversation
    monkeypatch.setattr(chat_runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(chat_runtime, "find_chat_request_turn", lambda *args, **kwargs: winner_turn)

    conversation, turn, created = _call(session)

    assert created is False
    assert conversation is winner_conversation
    assert turn is winner_turn
    assert "nested_rollback" in session.events
    assert session.events.index("nested_rollback") < session.events.index("read_winner_conversation")
    assert session.events[-1] == "commit"


def test_unrelated_integrity_error_is_not_absorbed(monkeypatch) -> None:
    session = _Session()
    _Repository.fail_constraint = "fk_ai_conversation_turns_conversation_organization"
    monkeypatch.setattr(chat_runtime, "AssistantRepository", _Repository)

    with pytest.raises(IntegrityError):
        _call(session)

    assert "nested_rollback" in session.events
    assert "commit" not in session.events
