from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from app.services import chat_runtime


class _FakeDb:
    def __init__(self, turn: Any) -> None:
        self.turn = turn
        self.statements: list[Any] = []
        self.commits = 0

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.turn

    def add(self, record: Any) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class _FakeRepository:
    sessions_created = 0
    runs_created = 0
    session: Any = None
    run: Any = None
    conversation: Any = None

    def __init__(self, db: _FakeDb) -> None:
        self.db = db

    def get_scoped_conversation(self, conversation_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        assert self.conversation.conversation_id == conversation_id
        assert self.conversation.organization_id == organization_id
        return self.conversation

    def get_scoped_assistant_session(
        self,
        assistant_session_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
    ) -> Any:
        if (
            self.session is not None
            and self.session.assistant_session_id == assistant_session_id
            and self.session.organization_id == organization_id
        ):
            return self.session
        return None

    def get_assistant_runtime_run(self, assistant_run_id: uuid.UUID) -> Any:
        if self.run is not None and self.run.assistant_run_id == assistant_run_id:
            return self.run
        return None

    def create_assistant_session(self, **kwargs: Any) -> Any:
        type(self).sessions_created += 1
        type(self).session = SimpleNamespace(
            assistant_session_id=uuid.uuid4(),
            assistant_id=kwargs["assistant_id"],
            organization_id=kwargs["execution_organization_id"],
        )
        return type(self).session

    def attach_conversation_session(
        self,
        *,
        conversation_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Any:
        assert self.conversation.conversation_id == conversation_id
        assert self.conversation.organization_id == organization_id
        self.conversation.assistant_session_id = assistant_session_id
        return self.conversation

    def create_assistant_runtime_run(self, **kwargs: Any) -> Any:
        type(self).runs_created += 1
        type(self).run = SimpleNamespace(
            assistant_run_id=uuid.uuid4(),
            assistant_session_id=kwargs["assistant_session_id"],
            assistant_id=kwargs["assistant_id"],
            organization_id=kwargs["execution_organization_id"],
            recovery_state="claimed",
            recovery_generation=1,
            run_status="planned",
            selected_search_mode=kwargs["selected_search_mode"],
            selected_runtime_domain=kwargs["selected_runtime_domain"],
        )
        return type(self).run


def test_same_chat_user_turn_claims_one_authoritative_run(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_turn_id = uuid.uuid4()
    turn = SimpleNamespace(
        conversation_turn_id=user_turn_id,
        organization_id=organization_id,
        assistant_id=assistant_id,
        conversation_id=conversation_id,
        turn_role="user",
        assistant_session_id=None,
        assistant_run_id=None,
        turn_metadata={"idempotency_key": "request-1"},
    )
    db = _FakeDb(turn)
    _FakeRepository.sessions_created = 0
    _FakeRepository.runs_created = 0
    _FakeRepository.session = None
    _FakeRepository.run = None
    _FakeRepository.conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=organization_id,
        assistant_session_id=None,
    )
    monkeypatch.setattr(chat_runtime, "AssistantRepository", _FakeRepository)
    monkeypatch.setattr(chat_runtime, "initialize_chat_run_claim", lambda db, run: 1)
    monkeypatch.setattr(chat_runtime, "mark_expired_provider_uncertain", lambda *args, **kwargs: False)
    monkeypatch.setattr(chat_runtime, "attempt_chat_run_takeover", lambda *args, **kwargs: None)

    first_session_id, first_run, first_claimed = chat_runtime._claim_idempotent_chat_execution(
        db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        user_turn_id=user_turn_id,
        requested_by="tester",
        message="inspection",
        context={"organization_id": str(organization_id)},
        metadata={"idempotency_key": "request-1"},
    )
    second_session_id, second_run, second_claimed = chat_runtime._claim_idempotent_chat_execution(
        db,
        organization_id=organization_id,
        assistant_id=assistant_id,
        user_turn_id=user_turn_id,
        requested_by="tester",
        message="inspection",
        context={"organization_id": str(organization_id)},
        metadata={"idempotency_key": "request-1"},
    )

    assert first_claimed is True
    assert second_claimed is False
    assert first_session_id == second_session_id
    assert first_run["assistant_run_id"] == second_run["assistant_run_id"]
    assert turn.assistant_run_id == uuid.UUID(first_run["assistant_run_id"])
    assert _FakeRepository.sessions_created == 1
    assert _FakeRepository.runs_created == 1
    assert len(db.statements) == 2
    assert all("FOR UPDATE" in str(statement) for statement in db.statements)
