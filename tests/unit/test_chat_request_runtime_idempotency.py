from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import Index
from sqlalchemy.exc import IntegrityError

from app.models.assistant_runtime import ConversationTurn
from app.services.conversation_runtime import (
    CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT,
    CONVERSATION_TURN_INDEX_CONSTRAINT,
    _is_chat_request_retry_conflict,
)


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    original = Exception("integrity error")
    original.diag = SimpleNamespace(constraint_name=constraint_name)  # type: ignore[attr-defined]
    return IntegrityError("statement", {}, original)


def test_conversation_turn_model_has_chat_request_unique_partial_index() -> None:
    indexes = {index.name: index for index in ConversationTurn.__table__.indexes if isinstance(index, Index)}

    index = indexes[CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT]
    assert index.unique is True
    assert [column.name for column in index.columns] == ["organization_id", "assistant_id", "request_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "request_id IS NOT NULL AND turn_role = 'user'"


def test_chat_request_unique_conflict_is_recoverable() -> None:
    error = _integrity_error(CHAT_REQUEST_IDEMPOTENCY_CONSTRAINT)

    assert _is_chat_request_retry_conflict(error) is True


def test_same_request_turn_position_race_is_recoverable() -> None:
    error = _integrity_error(CONVERSATION_TURN_INDEX_CONSTRAINT)

    assert _is_chat_request_retry_conflict(error) is True


def test_unrelated_integrity_error_is_not_recoverable() -> None:
    error = _integrity_error("fk_ai_conversation_turns_conversation_organization")

    assert _is_chat_request_retry_conflict(error) is False


def test_integrity_error_without_constraint_name_is_not_recoverable() -> None:
    error = _integrity_error(None)

    assert _is_chat_request_retry_conflict(error) is False
