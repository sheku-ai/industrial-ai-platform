from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.models.assistant_runtime import ConversationContextPackage, ConversationTurn
from app.repositories.assistant import AssistantRepository
from app.services import conversation_context_runtime


def _turn(
    *,
    turn_id: uuid.UUID,
    conversation_id: uuid.UUID,
    organization_id: uuid.UUID,
    turn_index: int,
    turn_role: str,
    turn_status: str = "recorded",
    input_text: str | None = None,
    output_text: str | None = None,
):
    return SimpleNamespace(
        conversation_turn_id=turn_id,
        conversation_id=conversation_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
        turn_index=turn_index,
        turn_role=turn_role,
        turn_status=turn_status,
        input_text=input_text,
        output_text=output_text,
    )


class _Repository:
    current_turn = None
    prior_turns = []
    existing = None
    created = None
    create_calls = 0
    requested_organization_ids = []

    def __init__(self, session) -> None:
        self.session = session

    @classmethod
    def reset(cls) -> None:
        cls.current_turn = None
        cls.prior_turns = []
        cls.existing = None
        cls.created = None
        cls.create_calls = 0
        cls.requested_organization_ids = []

    def get_scoped_conversation_turn(self, conversation_turn_id, *, organization_id):
        self.requested_organization_ids.append(organization_id)
        current = self.current_turn
        if current is None:
            return None
        if current.conversation_turn_id != conversation_turn_id:
            return None
        if current.organization_id != organization_id:
            return None
        return current

    def get_scoped_conversation_context_package(self, *, conversation_turn_id, organization_id):
        self.requested_organization_ids.append(organization_id)
        existing = self.existing
        if existing is None:
            return None
        if existing.conversation_turn_id != conversation_turn_id:
            return None
        if existing.organization_id != organization_id:
            return None
        return existing

    def list_scoped_conversation_turns_before(
        self,
        *,
        conversation_id,
        conversation_turn_index,
        organization_id,
    ):
        self.requested_organization_ids.append(organization_id)
        return [
            turn
            for turn in self.prior_turns
            if turn.conversation_id == conversation_id
            and turn.organization_id == organization_id
            and turn.turn_index < conversation_turn_index
        ]

    def create_conversation_context_package(self, **kwargs):
        type(self).create_calls += 1
        package = SimpleNamespace(
            conversation_context_package_id=uuid.uuid4(),
            ownership_scope="organization",
            created_at=None,
            updated_at=None,
            **kwargs,
        )
        type(self).created = package
        type(self).existing = package
        return package


def test_context_package_is_deterministic_and_idempotent(monkeypatch) -> None:
    _Repository.reset()
    monkeypatch.setattr(conversation_context_runtime, "AssistantRepository", _Repository)
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    prior_user_id = uuid.uuid4()
    prior_assistant_id = uuid.uuid4()
    failed_tool_id = uuid.uuid4()
    current_id = uuid.uuid4()
    _Repository.current_turn = _turn(
        turn_id=current_id,
        conversation_id=conversation_id,
        organization_id=organization_id,
        turn_index=3,
        turn_role="user",
        input_text="¿Y quién lo aprueba?",
    )
    _Repository.prior_turns = [
        _turn(
            turn_id=prior_user_id,
            conversation_id=conversation_id,
            organization_id=organization_id,
            turn_index=0,
            turn_role="user",
            input_text="Describe el proceso de aprobación.",
        ),
        _turn(
            turn_id=prior_assistant_id,
            conversation_id=conversation_id,
            organization_id=organization_id,
            turn_index=1,
            turn_role="assistant",
            turn_status="completed",
            output_text="El proceso requiere aprobación formal.",
        ),
        _turn(
            turn_id=failed_tool_id,
            conversation_id=conversation_id,
            organization_id=organization_id,
            turn_index=2,
            turn_role="tool",
            turn_status="failed",
            output_text="ignored",
        ),
    ]

    first = conversation_context_runtime.resolve_conversation_context_package(
        object(),
        conversation_turn_id=current_id,
        organization_id=organization_id,
        max_prior_turns=1,
    )
    second = conversation_context_runtime.resolve_conversation_context_package(
        object(),
        conversation_turn_id=current_id,
        organization_id=organization_id,
        max_prior_turns=1,
    )

    assert first is second
    assert _Repository.create_calls == 1
    assert first.current_user_message == "¿Y quién lo aprueba?"
    assert first.included_turn_ids == [str(prior_assistant_id)]
    assert first.retrieval_inputs["conversation_history"] == [
        {
            "conversation_turn_id": str(prior_assistant_id),
            "turn_index": 1,
            "turn_role": "assistant",
            "content": "El proceso requiere aprobación formal.",
        }
    ]
    assert first.excluded_turns == [
        {
            "conversation_turn_id": str(prior_user_id),
            "turn_index": 0,
            "reason": "context_window_limit",
        },
        {
            "conversation_turn_id": str(failed_tool_id),
            "turn_index": 2,
            "reason": "turn_status_not_context_eligible",
        },
    ]
    assert len(first.context_hash) == 64

    original_hash = first.context_hash
    _Repository.existing = None
    rebuilt = conversation_context_runtime.resolve_conversation_context_package(
        object(),
        conversation_turn_id=current_id,
        organization_id=organization_id,
        max_prior_turns=1,
    )
    assert rebuilt.context_hash == original_hash


def test_context_resolver_rejects_cross_organization_turn(monkeypatch) -> None:
    _Repository.reset()
    monkeypatch.setattr(conversation_context_runtime, "AssistantRepository", _Repository)
    owner_organization_id = uuid.uuid4()
    requested_organization_id = uuid.uuid4()
    current_id = uuid.uuid4()
    _Repository.current_turn = _turn(
        turn_id=current_id,
        conversation_id=uuid.uuid4(),
        organization_id=owner_organization_id,
        turn_index=0,
        turn_role="user",
        input_text="hello",
    )

    result = conversation_context_runtime.resolve_conversation_context_package(
        object(),
        conversation_turn_id=current_id,
        organization_id=requested_organization_id,
    )

    assert result is None
    assert _Repository.create_calls == 0
    assert _Repository.requested_organization_ids == [requested_organization_id]


def test_repository_prior_turn_query_is_scoped_and_ordered() -> None:
    captured = SimpleNamespace(statement=None)

    class _Scalars:
        def all(self):
            return []

    class _Session:
        def scalars(self, statement):
            captured.statement = statement
            return _Scalars()

    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    result = AssistantRepository(_Session()).list_scoped_conversation_turns_before(
        conversation_id=conversation_id,
        conversation_turn_index=7,
        organization_id=organization_id,
    )

    assert result == []
    sql = str(
        captured.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"conversation_turns.conversation_id = '{conversation_id}'" in sql
    assert f"conversation_turns.organization_id = '{organization_id}'" in sql
    assert "conversation_turns.ownership_scope = 'organization'" in sql
    assert "conversation_turns.turn_index < 7" in sql
    assert "ORDER BY ai.conversation_turns.turn_index ASC" in sql


def test_context_package_model_enforces_scoped_turn_identity() -> None:
    turn_unique = {
        constraint.name: constraint
        for constraint in ConversationTurn.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_ai_conversation_turns_id_conversation_organization" in turn_unique

    context_constraints = ConversationContextPackage.__table__.constraints
    scoped_fk = next(
        constraint
        for constraint in context_constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_ai_conversation_context_packages_scoped_turn"
    )
    assert [column.name for column in scoped_fk.columns] == [
        "conversation_turn_id",
        "conversation_id",
        "organization_id",
    ]
    assert [element.target_fullname for element in scoped_fk.elements] == [
        "ai.conversation_turns.conversation_turn_id",
        "ai.conversation_turns.conversation_id",
        "ai.conversation_turns.organization_id",
    ]
