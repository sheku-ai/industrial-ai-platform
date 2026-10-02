from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.models.assistant_runtime import ConversationInteractionDecision
from app.models.conversation_intent_model import (
    ConversationIntentClassificationEvidence,
    ConversationIntentModel,
)
from app.repositories.conversation_intent_model import ConversationIntentModelRepository
from app.services import conversation_intent_model_runtime
from app.services.conversation_intent_engine import IntentClassificationResult, classify_intent
from app.services.conversation_intent_model_runtime import EffectiveIntentModel


def _constraint_sql(model: type[Any]) -> str:
    return " ".join(
        str(constraint.sqltext) for constraint in model.__table__.constraints if isinstance(constraint, CheckConstraint)
    )


def _model(
    scope_type: str,
    *,
    organization_id: uuid.UUID | None = None,
    organization_node_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        intent_model_id=uuid.uuid4(),
        organization_id=organization_id,
        organization_node_id=organization_node_id,
        ownership_scope="global" if scope_type == "community" else "organization",
        scope_type=scope_type,
        data_origin="operational",
        model_family="conversation_intent",
        provider="community.setfit",
        model_version="1.0.0",
        model_status="active",
        artifact_reference="artifact://intent/1.0.0",
        artifact_hash="a" * 64,
        model_metadata={},
        created_at=None,
        updated_at=None,
    )


def test_intent_model_schema_enforces_all_scope_contracts_and_active_uniqueness() -> None:
    sql = _constraint_sql(ConversationIntentModel)
    assert "scope_type = 'community'" in sql
    assert "organization_id IS NULL" in sql
    assert "scope_type = 'organization'" in sql
    assert "organization_id IS NOT NULL" in sql
    assert "scope_type = 'organization_node'" in sql
    assert "organization_node_id IS NOT NULL" in sql
    assert "char_length(artifact_hash) = 64" in sql

    scoped_node = next(
        constraint
        for constraint in ConversationIntentModel.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_ai_conversation_intent_models_scoped_node"
    )
    assert [column.name for column in scoped_node.columns] == ["organization_id", "organization_node_id"]
    assert [element.target_fullname for element in scoped_node.elements] == [
        "core.organization_nodes.organization_id",
        "core.organization_nodes.id",
    ]

    active_indexes = {
        index.name: index
        for index in ConversationIntentModel.__table__.indexes
        if index.name.startswith("uq_ai_conversation_intent_models_active_")
    }
    assert set(active_indexes) == {
        "uq_ai_conversation_intent_models_active_community_family",
        "uq_ai_conversation_intent_models_active_organization_family",
        "uq_ai_conversation_intent_models_active_node_family",
    }
    assert all(isinstance(index, Index) and index.unique for index in active_indexes.values())
    assert all(index.dialect_options["postgresql"]["where"] is not None for index in active_indexes.values())


def test_classification_evidence_schema_is_immutable_scoped_and_unique_per_turn() -> None:
    columns = ConversationIntentClassificationEvidence.__table__.columns
    assert "updated_at" not in columns
    assert columns.organization_id.nullable is False
    assert columns.predicted_parameters.nullable is False

    unique_names = {
        constraint.name
        for constraint in ConversationIntentClassificationEvidence.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_ai_intent_classification_evidence_org_turn" in unique_names

    foreign_keys = {
        constraint.name: constraint
        for constraint in ConversationIntentClassificationEvidence.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert [column.name for column in foreign_keys["fk_ai_intent_classification_evidence_scoped_turn"].columns] == [
        "conversation_turn_id",
        "conversation_id",
        "organization_id",
    ]
    assert [column.name for column in foreign_keys["fk_ai_intent_classification_evidence_scoped_context"].columns] == [
        "conversation_context_package_id",
        "organization_id",
        "conversation_turn_id",
    ]
    assert {"classification_evidence_id", "sub_intent", "intent_parameters"}.issubset(
        ConversationInteractionDecision.__table__.columns.keys()
    )
    decision_classification_fk = next(
        constraint
        for constraint in ConversationInteractionDecision.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_ai_conversation_interaction_decisions_classification"
    )
    assert [element.target_fullname for element in decision_classification_fk.elements] == [
        "ai.conversation_intent_classification_evidence.classification_evidence_id"
    ]


def test_effective_model_resolution_uses_node_then_organization_then_community(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node_model = _model("organization_node", organization_id=organization_id, organization_node_id=node_id)
    organization_model = _model("organization", organization_id=organization_id)
    community_model = _model("community")
    repository = ConversationIntentModelRepository(SimpleNamespace())
    calls: list[str] = []

    monkeypatch.setattr(
        repository,
        "get_active_organization_node_model",
        lambda *args: calls.append("node") or node_model,
    )
    monkeypatch.setattr(
        repository,
        "get_active_organization_model",
        lambda *args: calls.append("organization") or organization_model,
    )
    monkeypatch.setattr(
        repository,
        "get_active_community_model",
        lambda *args: calls.append("community") or community_model,
    )

    assert repository.resolve_effective_model(organization_id, node_id) is node_model
    assert calls == ["node"]

    calls.clear()
    monkeypatch.setattr(
        repository,
        "get_active_organization_node_model",
        lambda *args: calls.append("node") or None,
    )
    assert repository.resolve_effective_model(organization_id, node_id) is organization_model
    assert calls == ["node", "organization"]

    calls.clear()
    monkeypatch.setattr(
        repository,
        "get_active_organization_model",
        lambda *args: calls.append("organization") or None,
    )
    assert repository.resolve_effective_model(organization_id, node_id) is community_model
    assert calls == ["node", "organization", "community"]

    calls.clear()
    monkeypatch.setattr(
        repository,
        "get_active_community_model",
        lambda *args: calls.append("community") or None,
    )
    assert repository.resolve_effective_model(organization_id, node_id) is None
    assert calls == ["node", "organization", "community"]


def test_classification_rejects_cross_organization_model_scope() -> None:
    requested_organization_id = uuid.uuid4()
    other_organization_model = _model("organization", organization_id=uuid.uuid4())

    with pytest.raises(ValueError, match="organization scope is inconsistent"):
        ConversationIntentModelRepository._validate_model_scope(
            other_organization_model,
            organization_id=requested_organization_id,
            requested_organization_node_id=None,
        )


def test_classification_accepts_community_organization_and_node_scopes() -> None:
    organization_id = uuid.uuid4()
    node_id = uuid.uuid4()

    ConversationIntentModelRepository._validate_model_scope(
        _model("community"),
        organization_id=organization_id,
        requested_organization_node_id=None,
    )
    ConversationIntentModelRepository._validate_model_scope(
        _model("organization", organization_id=organization_id),
        organization_id=organization_id,
        requested_organization_node_id=None,
    )
    ConversationIntentModelRepository._validate_model_scope(
        _model("organization_node", organization_id=organization_id, organization_node_id=node_id),
        organization_id=organization_id,
        requested_organization_node_id=node_id,
    )


def test_active_model_queries_cannot_select_cross_organization_records() -> None:
    statements: list[Any] = []

    class Session:
        def scalar(self, statement: Any) -> None:
            statements.append(statement)
            return None

    organization_id = uuid.uuid4()
    node_id = uuid.uuid4()
    repository = ConversationIntentModelRepository(Session())
    repository.get_active_organization_node_model(organization_id, node_id, "conversation_intent")
    repository.get_active_organization_model(organization_id, "conversation_intent")
    repository.get_active_community_model("conversation_intent")

    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in statements
    ]
    assert f"organization_id = '{organization_id}'" in sql[0]
    assert f"organization_node_id = '{node_id}'" in sql[0]
    assert f"organization_id = '{organization_id}'" in sql[1]
    assert "organization_id IS NULL" in sql[2]


def test_effective_model_runtime_serializes_postgresql_authority(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    record = _model("organization", organization_id=organization_id)

    class Repository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def resolve_effective_model(self, requested_organization_id: uuid.UUID, **kwargs: Any) -> Any:
            assert requested_organization_id == organization_id
            return record

    monkeypatch.setattr(conversation_intent_model_runtime, "ConversationIntentModelRepository", Repository)

    resolved = conversation_intent_model_runtime.resolve_effective_intent_model(
        object(),
        organization_id=organization_id,
    )

    assert resolved is not None
    assert resolved.intent_model_id == record.intent_model_id
    assert (
        conversation_intent_model_runtime.effective_intent_model_to_dict(resolved)["postgresql_source_of_truth"] is True
    )


def test_intent_engine_preserves_structured_candidate_from_effective_model(monkeypatch: Any) -> None:
    organization_id = uuid.uuid4()
    effective_model = EffectiveIntentModel(
        intent_model_id=uuid.uuid4(),
        model_family="conversation_intent",
        provider="community.setfit",
        model_version="1.0.0",
        scope_type="organization",
        organization_id=organization_id,
        organization_node_id=None,
        artifact_reference="artifact://intent/1.0.0",
        artifact_hash="a" * 64,
    )

    class Model:
        labels = ["knowledge_query", "response_refinement"]

        def predict_proba(self, text: str, *, as_numpy: bool) -> list[float]:
            return [0.07, 0.93]

    from app.services import conversation_intent_engine

    monkeypatch.setattr(conversation_intent_engine, "_load_setfit_model", lambda *args: Model())

    candidate = classify_intent(
        effective_model=effective_model,
        current_user_message="modify the previous answer",
    )

    assert candidate is not None
    assert candidate.intent == "response_refinement"
    assert candidate.sub_intent is None
    assert candidate.intent_parameters == {}
    assert candidate.intent_model_id == effective_model.intent_model_id
    assert candidate.model_family == effective_model.model_family
    assert candidate.provider == effective_model.provider
    assert candidate.model_version == effective_model.model_version
    assert candidate.artifact_reference == effective_model.artifact_reference
    assert candidate.artifact_hash == effective_model.artifact_hash

    structured = IntentClassificationResult(
        intent="response_refinement",
        sub_intent="structured-sub-intent",
        intent_parameters={"structured": True},
        confidence=0.93,
        provider=effective_model.provider,
        model_version=effective_model.model_version,
        intent_model_id=effective_model.intent_model_id,
        model_family=effective_model.model_family,
        model_scope_type=effective_model.scope_type,
        artifact_reference=effective_model.artifact_reference,
        artifact_hash=effective_model.artifact_hash,
        resolution_method="community.setfit.classification",
    )
    assert structured.sub_intent == "structured-sub-intent"
    assert structured.intent_parameters == {"structured": True}
