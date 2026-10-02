from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import conversation_interaction_plan_runtime as runtime


class _NestedTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False


class _FakeSession:
    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()


class _ConstraintDiag:
    constraint_name = runtime.INTERACTION_PLAN_IDEMPOTENCY_CONSTRAINT


class _ConstraintOrig(Exception):
    diag = _ConstraintDiag()


def _evidence() -> tuple[Any, Any]:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()
    context_package_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    context = SimpleNamespace(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        context_hash="context-hash",
        included_turn_ids=[],
    )
    decision = SimpleNamespace(
        interaction_decision_id=decision_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=conversation_turn_id,
        conversation_context_package_id=context_package_id,
        data_origin="operational",
        intent="knowledge_query",
        target_runtime="assistant.enterprise_search",
        referenced_turn_ids=[],
        conversation_context_required=False,
        retrieval_required=True,
        generation_required=True,
        decision_hash="decision-hash",
    )
    return context, decision


def test_concurrent_plan_creation_recovers_authoritative_winner(monkeypatch: Any) -> None:
    context, decision = _evidence()
    winner = SimpleNamespace(
        interaction_plan_id=uuid.uuid4(),
        organization_id=decision.organization_id,
        conversation_id=decision.conversation_id,
        conversation_turn_id=decision.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        interaction_decision_id=decision.interaction_decision_id,
    )

    class Repository:
        reads = 0

        def __init__(self, session: Any) -> None:
            self.session = session

        def get_for_turn(self, *, organization_id: uuid.UUID, conversation_turn_id: uuid.UUID) -> Any:
            assert organization_id == decision.organization_id
            assert conversation_turn_id == decision.conversation_turn_id
            type(self).reads += 1
            return None if type(self).reads == 1 else winner

        def create(self, **kwargs: Any) -> Any:
            raise IntegrityError("insert", {}, _ConstraintOrig())

    draft = SimpleNamespace()
    monkeypatch.setattr(runtime, "ConversationInteractionPlanRepository", Repository)
    monkeypatch.setattr(runtime, "build_interaction_plan", lambda **kwargs: draft)

    resolved = runtime.resolve_persisted_interaction_plan(
        _FakeSession(),
        context_package=context,
        interaction_decision=decision,
    )

    assert resolved is winner
    assert Repository.reads == 2


def test_unrelated_integrity_error_is_not_treated_as_idempotency(monkeypatch: Any) -> None:
    context, decision = _evidence()

    class OtherDiag:
        constraint_name = "some_other_constraint"

    class OtherOrig(Exception):
        diag = OtherDiag()

    class Repository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_for_turn(self, **kwargs: Any) -> None:
            return None

        def create(self, **kwargs: Any) -> Any:
            raise IntegrityError("insert", {}, OtherOrig())

    monkeypatch.setattr(runtime, "ConversationInteractionPlanRepository", Repository)
    monkeypatch.setattr(runtime, "build_interaction_plan", lambda **kwargs: SimpleNamespace())

    with pytest.raises(IntegrityError):
        runtime.resolve_persisted_interaction_plan(
            _FakeSession(),
            context_package=context,
            interaction_decision=decision,
        )


def test_execution_directive_is_organization_scoped(monkeypatch: Any) -> None:
    expected_organization_id = uuid.uuid4()
    other_organization_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()

    class Repository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_for_turn(self, *, organization_id: uuid.UUID, conversation_turn_id: uuid.UUID) -> Any:
            if organization_id != expected_organization_id:
                return None
            return SimpleNamespace(
                interaction_plan_id=uuid.uuid4(),
                organization_id=expected_organization_id,
                conversation_turn_id=conversation_turn_id,
                planned_action="enterprise_search",
                target_runtime="assistant.enterprise_search",
                enterprise_search_required=True,
                generation_required=True,
                deterministic_response_allowed=False,
            )

    monkeypatch.setattr(runtime, "ConversationInteractionPlanRepository", Repository)

    directive = runtime.resolve_interaction_execution_directive(
        object(),
        organization_id=expected_organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    assert directive.organization_id == expected_organization_id

    with pytest.raises(ValueError, match="authoritative persisted interaction plan is unavailable"):
        runtime.resolve_interaction_execution_directive(
            object(),
            organization_id=other_organization_id,
            conversation_turn_id=conversation_turn_id,
        )


def test_enterprise_search_requires_explicit_persisted_authorization(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    conversation_turn_id = uuid.uuid4()
    rejected = runtime.InteractionExecutionDirective(
        interaction_plan_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
        planned_action="reuse_persisted_citations",
        target_runtime="assistant.enterprise_search",
        enterprise_search_required=False,
        generation_required=True,
        deterministic_response_allowed=False,
    )
    monkeypatch.setattr(runtime, "resolve_interaction_execution_directive", lambda *args, **kwargs: rejected)

    with pytest.raises(runtime.InteractionExecutionNotPlannedError):
        runtime.require_enterprise_search_execution(
            object(),
            organization_id=organization_id,
            conversation_turn_id=conversation_turn_id,
        )


def test_existing_plan_lineage_mismatch_is_rejected() -> None:
    context, decision = _evidence()
    plan = SimpleNamespace(
        organization_id=uuid.uuid4(),
        conversation_id=decision.conversation_id,
        conversation_turn_id=decision.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
        interaction_decision_id=decision.interaction_decision_id,
    )

    with pytest.raises(ValueError, match="organization_id lineage is inconsistent"):
        runtime._validate_existing_plan(
            plan,
            context_package=context,
            interaction_decision=decision,
        )
