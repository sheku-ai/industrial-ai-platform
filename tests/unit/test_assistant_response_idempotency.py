from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError

from app.models.assistant_runtime import AssistantResponse
from app.services.assistant_response_runtime import (
    ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT,
    _is_assistant_response_idempotency_conflict,
)


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    original = Exception("integrity error")
    original.diag = SimpleNamespace(constraint_name=constraint_name)  # type: ignore[attr-defined]
    return IntegrityError("statement", {}, original)


def test_assistant_response_model_enforces_citation_verification_uniqueness() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in AssistantResponse.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    constraint = constraints[ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT]
    assert [column.name for column in constraint.columns] == ["citation_verification_id"]


def test_expected_assistant_response_idempotency_conflict_is_recognized() -> None:
    error = _integrity_error(ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT)

    assert _is_assistant_response_idempotency_conflict(error) is True


def test_unrelated_integrity_error_is_not_treated_as_idempotent() -> None:
    error = _integrity_error("fk_ai_assistant_responses_llm_execution")

    assert _is_assistant_response_idempotency_conflict(error) is False


def test_integrity_error_without_postgresql_constraint_is_not_treated_as_idempotent() -> None:
    error = _integrity_error(None)

    assert _is_assistant_response_idempotency_conflict(error) is False
