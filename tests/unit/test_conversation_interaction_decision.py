from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models.assistant_runtime import (
    ConversationContextPackage,
    ConversationInteractionDecision,
)
from app.repositories.assistant import AssistantRepository
from app.services import conversation_interaction_runtime


class _NestedTransaction:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def begin_nested(self):
        return _NestedTransaction()


class _Repository:
    context_package = None
    configuration = None
    decision = None
    configuration_creates = 0
    decision_creates = 0
    configuration_scope_locks = 0
    requested_organization_ids = []

    def __init__(self, session) -> None:
        self.session = session

    @classmethod
    def reset(cls) -> None:
        cls.context_package = None
        cls.configuration = None
        cls.decision = None
        cls.configuration_creates = 0
        cls.decision_creates = 0
        cls.configuration_scope_locks = 0
        cls.requested_organization_ids = []

    def lock_conversation_routing_configuration_scope(self, *, organization_id):
        type(self).configuration_scope_locks += 1
        self.requested_organization_ids.append(organization_id)
        return SimpleNamespace(id=organization_id)

    def get_active_conversation_routing_configuration(self, *, organization_id):
        self.requested_organization_ids.append(organization_id)
        configuration = self.configuration
        if configuration is None or configuration.organization_id != organization_id:
            return None
        return configuration

    def create_conversation_routing_configuration(self, **kwargs):
        type(self).configuration_creates += 1
        configuration = SimpleNamespace(
            routing_configuration_id=uuid.uuid4(),
            ownership_scope="organization",
            configuration_status="active",
            created_at=None,
            updated_at=None,
            **kwargs,
        )
        type(self).configuration = configuration
        return configuration

    def get_scoped_conversation_interaction_decision(self, *, conversation_turn_id, organization_id):
        self.requested_organization_ids.append(organization_id)
        decision = self.decision
        if decision is None:
            return None
        if decision.conversation_turn_id != conversation_turn_id:
            return None
        if decision.organization_id != organization_id:
            return None
        return decision

    def get_scoped_conversation_context_package(self, *, conversation_turn_id, organization_id):
        self.requested_organization_ids.append(organization_id)
        context = self.context_package
        if context is None:
            return None
        if context.conversation_turn_id != conversation_turn_id:
            return None
        if context.organization_id != organization_id:
            return None
        return context

    def create_conversation_interaction_decision(self, **kwargs):
        type(self).decision_creates += 1
        decision = SimpleNamespace(
            interaction_decision_id=uuid.uuid4(),
            ownership_scope="organization",
            created_at=None,
            updated_at=None,
            **kwargs,
        )
        type(self).decision = decision
        return decision


def _context(*, organization_id, conversation_id, turn_id):
    return SimpleNamespace(
        conversation_context_package_id=uuid.uuid4(),
        organization_id=organization_id,
        data_origin="operational",
        conversation_id=conversation_id,
        conversation_turn_id=turn_id,
        context_hash="c" * 64,
        current_user_message="¿Qué política aplica al proceso de aprobación?",
        retrieval_inputs={
            "current_user_message": "¿Qué política aplica al proceso de aprobación?",
            "conversation_history": [],
        },
    )


def test_default_contract_contains_mandatory_intents_and_single_community_provider() -> None:
    payload = conversation_interaction_runtime._default_configuration_payload()

    assert [item["intent"] for item in payload["intent_catalog"]] == list(
        conversation_interaction_runtime.INITIAL_INTENTS
    )
    assert payload["configuration_version"] == "conversation-routing.v2"
    assert payload["provider_chain"] == [{"provider": "community.setfit", "enabled": True, "required": False}]
    assert payload["semantic_configuration"]["provider"] == "community.setfit"
    assert payload["semantic_configuration"]["local_files_only"] is True
    assert "model_reference" not in payload["semantic_configuration"]
    assert "model_version" not in payload["semantic_configuration"]
    assert payload["semantic_configuration"]["llm_required"] is False
    assert payload["semantic_configuration"]["vector_database_required"] is False
    assert payload["fallback_behavior"]["provider"] == "system.safe_fallback"


def test_interaction_decision_is_persisted_deterministically_and_idempotently(monkeypatch) -> None:
    _Repository.reset()
    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_persisted_interaction_plan",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    _Repository.context_package = _context(
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    classification_evidence = SimpleNamespace(
        classification_evidence_id=uuid.uuid4(),
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=turn_id,
        conversation_context_package_id=_Repository.context_package.conversation_context_package_id,
        predicted_intent="response_refinement",
        predicted_sub_intent="structured-sub-intent",
        predicted_parameters={"structured": True},
        confidence=0.94,
        resolution_method="community.setfit.classification",
        resolution_provider="community.setfit",
    )
    classification_calls = 0

    def resolve_classification(*args, **kwargs):
        nonlocal classification_calls
        classification_calls += 1
        return classification_evidence

    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_intent_classification",
        resolve_classification,
    )

    first = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )
    second = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )

    assert first is second
    assert _Repository.configuration_creates == 1
    assert _Repository.configuration_scope_locks == 1
    assert _Repository.decision_creates == 1
    assert classification_calls == 1
    assert first.classification_evidence_id == classification_evidence.classification_evidence_id
    assert first.intent == "response_refinement"
    assert first.sub_intent == "structured-sub-intent"
    assert first.intent_parameters == {"structured": True}
    assert first.confidence == 0.94
    assert first.resolution_method == "community.setfit.classification"
    assert first.resolution_provider == "community.setfit"
    assert first.retrieval_required is False
    assert first.generation_required is True
    assert first.conversation_context_required is True
    assert first.embedding_used is False
    assert first.slm_used is False
    assert len(first.input_hash) == 64
    assert len(first.decision_hash) == 64

    original_input_hash = first.input_hash
    original_decision_hash = first.decision_hash
    _Repository.decision = None
    rebuilt = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )
    assert classification_calls == 2
    assert rebuilt.input_hash == original_input_hash
    assert rebuilt.decision_hash == original_decision_hash


def test_interaction_decision_technical_fallback_has_no_classification_evidence(monkeypatch) -> None:
    _Repository.reset()
    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_intent_classification",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_persisted_interaction_plan",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    _Repository.context_package = _context(
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    decision = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )

    assert decision.classification_evidence_id is None
    assert decision.sub_intent is None
    assert decision.intent_parameters == {}
    assert decision.intent == "knowledge_query"
    assert decision.confidence == 0.0
    assert decision.resolution_method == "configured.fallback"
    assert decision.resolution_provider == "system.safe_fallback"
    assert decision.embedding_used is False
    assert decision.slm_used is False


def test_interaction_decision_rejects_cross_organization_context(monkeypatch) -> None:
    _Repository.reset()
    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", _Repository)
    owner_organization_id = uuid.uuid4()
    requested_organization_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    _Repository.context_package = _context(
        organization_id=owner_organization_id,
        conversation_id=uuid.uuid4(),
        turn_id=turn_id,
    )
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_context_package",
        lambda *args, **kwargs: None,
    )

    result = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=requested_organization_id,
    )

    assert result is None
    assert _Repository.configuration_creates == 0
    assert _Repository.decision_creates == 0
    assert requested_organization_id in _Repository.requested_organization_ids


class _DecisionIdempotencyDiag:
    constraint_name = conversation_interaction_runtime.DECISION_IDEMPOTENCY_CONSTRAINT


class _DecisionIdempotencyOrig(Exception):
    diag = _DecisionIdempotencyDiag()


def test_concurrent_decision_creation_recovers_scoped_winner(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    context = _context(
        organization_id=organization_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    winner = SimpleNamespace(
        organization_id=organization_id,
        conversation_id=conversation_id,
        conversation_turn_id=turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
    )

    class ConcurrentRepository(_Repository):
        decision_reads = 0

        def get_scoped_conversation_interaction_decision(self, **kwargs):
            type(self).decision_reads += 1
            return None if type(self).decision_reads == 1 else winner

        def create_conversation_interaction_decision(self, **kwargs):
            raise IntegrityError("insert", {}, _DecisionIdempotencyOrig())

    ConcurrentRepository.reset()
    ConcurrentRepository.context_package = context
    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", ConcurrentRepository)
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_intent_classification",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_persisted_interaction_plan",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    resolved = conversation_interaction_runtime.resolve_interaction_decision(
        _Session(),
        conversation_turn_id=turn_id,
        organization_id=organization_id,
    )

    assert resolved is winner
    assert ConcurrentRepository.decision_reads == 2


def test_unrelated_decision_integrity_error_propagates(monkeypatch) -> None:
    class OtherDiag:
        constraint_name = "unrelated_constraint"

    class OtherOrig(Exception):
        diag = OtherDiag()

    class FailingRepository(_Repository):
        def create_conversation_interaction_decision(self, **kwargs):
            raise IntegrityError("insert", {}, OtherOrig())

    FailingRepository.reset()
    organization_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    FailingRepository.context_package = _context(
        organization_id=organization_id,
        conversation_id=uuid.uuid4(),
        turn_id=turn_id,
    )
    monkeypatch.setattr(conversation_interaction_runtime, "AssistantRepository", FailingRepository)
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_conversation_intent_classification",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        conversation_interaction_runtime,
        "resolve_persisted_interaction_plan",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    with pytest.raises(IntegrityError):
        conversation_interaction_runtime.resolve_interaction_decision(
            _Session(),
            conversation_turn_id=turn_id,
            organization_id=organization_id,
        )


def test_interaction_models_enforce_scoped_lineage() -> None:
    context_unique = {
        constraint.name: constraint
        for constraint in ConversationContextPackage.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_ai_conversation_context_packages_id_organization_turn" in context_unique

    decision_constraints = ConversationInteractionDecision.__table__.constraints
    scoped_context = next(
        constraint
        for constraint in decision_constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_ai_conversation_interaction_decisions_scoped_context"
    )
    assert [column.name for column in scoped_context.columns] == [
        "conversation_context_package_id",
        "organization_id",
        "conversation_turn_id",
    ]
    scoped_configuration = next(
        constraint
        for constraint in decision_constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_ai_conversation_interaction_decisions_scoped_configuration"
    )
    assert [column.name for column in scoped_configuration.columns] == [
        "routing_configuration_id",
        "organization_id",
    ]


def test_repository_configuration_and_decision_queries_are_organization_scoped() -> None:
    captured = SimpleNamespace(statements=[])

    class _Session:
        def scalar(self, statement):
            captured.statements.append(statement)
            return None

    organization_id = uuid.uuid4()
    repository = AssistantRepository(_Session())
    repository.lock_conversation_routing_configuration_scope(organization_id=organization_id)
    repository.get_active_conversation_routing_configuration(organization_id=organization_id)
    repository.get_scoped_conversation_interaction_decision(
        conversation_turn_id=uuid.uuid4(),
        organization_id=organization_id,
    )

    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in captured.statements
    ]
    assert f"organizations.id = '{organization_id}'" in sql[0]
    assert "FOR UPDATE" in sql[0]
    assert all(f"organization_id = '{organization_id}'" in statement for statement in sql[1:])
    assert "configuration_status = 'active'" in sql[1]
    assert "ownership_scope = 'organization'" in sql[1]
    assert "ownership_scope = 'organization'" in sql[2]


def test_legacy_interaction_decision_serialization_defaults_structured_fields() -> None:
    record = SimpleNamespace(
        interaction_decision_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        ownership_scope="organization",
        data_origin="operational",
        conversation_id=uuid.uuid4(),
        conversation_turn_id=uuid.uuid4(),
        conversation_context_package_id=uuid.uuid4(),
        routing_configuration_id=uuid.uuid4(),
        intent="knowledge_query",
        confidence=0.0,
        resolution_method="configured.fallback",
        resolution_provider="system.safe_fallback",
        referenced_turn_ids=[],
        conversation_context_required=False,
        retrieval_required=True,
        generation_required=True,
        target_runtime="assistant.enterprise_search",
        embedding_used=False,
        slm_used=False,
        router_version="conversation-router.contract.v2",
        input_hash="a" * 64,
        decision_hash="b" * 64,
        created_at=None,
        updated_at=None,
    )

    payload = conversation_interaction_runtime.interaction_decision_to_dict(record)

    assert payload["classification_evidence_id"] is None
    assert payload["sub_intent"] is None
    assert payload["intent_parameters"] == {}
