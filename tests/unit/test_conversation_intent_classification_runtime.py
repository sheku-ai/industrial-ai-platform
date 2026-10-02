from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import conversation_intent_classification_runtime as runtime
from app.services.conversation_intent_engine import IntentClassificationResult
from app.services.conversation_intent_model_runtime import EffectiveIntentModel


class _NestedTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False


class _Session:
    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        organization_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        conversation_turn_id=uuid.uuid4(),
        conversation_context_package_id=uuid.uuid4(),
        ownership_scope="organization",
        data_origin="operational",
        context_hash="c" * 64,
        current_user_message="Refine the previous response",
        retrieval_inputs={
            "current_user_message": "Refine the previous response",
            "conversation_history": [{"turn_role": "assistant", "content": "Prior response"}],
        },
    )


def _effective_model(organization_id: uuid.UUID) -> EffectiveIntentModel:
    return EffectiveIntentModel(
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


def _classification_result(effective_model: EffectiveIntentModel) -> IntentClassificationResult:
    return IntentClassificationResult(
        intent="response_refinement",
        sub_intent="structured-sub-intent",
        intent_parameters={"structured": True},
        confidence=0.94,
        provider=effective_model.provider,
        model_version=effective_model.model_version,
        intent_model_id=effective_model.intent_model_id,
        model_family=effective_model.model_family,
        model_scope_type=effective_model.scope_type,
        artifact_reference=effective_model.artifact_reference,
        artifact_hash=effective_model.artifact_hash,
        resolution_method="community.setfit.classification",
    )


def test_classification_persists_structured_lineage_hashes_and_reuses_evidence(monkeypatch: Any) -> None:
    context = _context()
    effective_model = _effective_model(context.organization_id)

    class AssistantRepository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_scoped_conversation_context_package(self, **kwargs: Any) -> Any:
            assert kwargs["organization_id"] == context.organization_id
            assert kwargs["conversation_turn_id"] == context.conversation_turn_id
            return context

    class IntentRepository:
        existing: Any = None
        creates: list[dict[str, Any]] = []

        def __init__(self, session: Any) -> None:
            self.session = session

        def get_classification_for_turn(self, organization_id: uuid.UUID, conversation_turn_id: uuid.UUID) -> Any:
            assert organization_id == context.organization_id
            assert conversation_turn_id == context.conversation_turn_id
            return type(self).existing

        def create_classification_evidence(self, **kwargs: Any) -> Any:
            type(self).creates.append(kwargs)
            record = SimpleNamespace(
                classification_evidence_id=uuid.uuid4(),
                ownership_scope="organization",
                created_at=None,
                **kwargs,
            )
            type(self).existing = record
            return record

    classifier_calls = 0

    def classify(**kwargs: Any) -> IntentClassificationResult:
        nonlocal classifier_calls
        classifier_calls += 1
        assert kwargs["effective_model"] == effective_model
        return _classification_result(effective_model)

    monkeypatch.setattr(runtime, "AssistantRepository", AssistantRepository)
    monkeypatch.setattr(runtime, "ConversationIntentModelRepository", IntentRepository)
    monkeypatch.setattr(runtime, "resolve_effective_intent_model", lambda *args, **kwargs: effective_model)
    monkeypatch.setattr(runtime, "classify_intent", classify)

    first = runtime.resolve_conversation_intent_classification(
        _Session(),
        organization_id=context.organization_id,
        conversation_turn_id=context.conversation_turn_id,
    )
    second = runtime.resolve_conversation_intent_classification(
        _Session(),
        organization_id=context.organization_id,
        conversation_turn_id=context.conversation_turn_id,
    )

    assert second is first
    assert classifier_calls == 1
    assert len(IntentRepository.creates) == 1
    persisted = IntentRepository.creates[0]
    assert persisted["organization_id"] == context.organization_id
    assert persisted["conversation_id"] == context.conversation_id
    assert persisted["conversation_context_package_id"] == context.conversation_context_package_id
    assert persisted["intent_model_id"] == effective_model.intent_model_id
    assert persisted["model_family"] == effective_model.model_family
    assert persisted["artifact_reference"] == effective_model.artifact_reference
    assert persisted["artifact_hash"] == effective_model.artifact_hash
    assert persisted["predicted_intent"] == "response_refinement"
    assert persisted["predicted_sub_intent"] == "structured-sub-intent"
    assert persisted["predicted_parameters"] == {"structured": True}
    assert persisted["model_version"] == effective_model.model_version
    assert persisted["model_scope_type"] == effective_model.scope_type
    assert len(persisted["input_hash"]) == 64
    assert len(persisted["classification_hash"]) == 64

    first_hashes = (persisted["input_hash"], persisted["classification_hash"])
    IntentRepository.existing = None
    IntentRepository.creates.clear()
    rebuilt = runtime.resolve_conversation_intent_classification(
        _Session(),
        organization_id=context.organization_id,
        conversation_turn_id=context.conversation_turn_id,
    )
    assert rebuilt is not None
    assert (
        IntentRepository.creates[0]["input_hash"],
        IntentRepository.creates[0]["classification_hash"],
    ) == first_hashes


class _IdempotencyDiag:
    constraint_name = runtime.CLASSIFICATION_EVIDENCE_IDEMPOTENCY_CONSTRAINT


class _IdempotencyOrig(Exception):
    diag = _IdempotencyDiag()


def test_concurrent_classification_duplicate_recovers_authoritative_winner(monkeypatch: Any) -> None:
    context = _context()
    effective_model = _effective_model(context.organization_id)
    winner = SimpleNamespace(
        classification_evidence_id=uuid.uuid4(),
        ownership_scope="organization",
        organization_id=context.organization_id,
        conversation_id=context.conversation_id,
        conversation_turn_id=context.conversation_turn_id,
        conversation_context_package_id=context.conversation_context_package_id,
    )

    class AssistantRepository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_scoped_conversation_context_package(self, **kwargs: Any) -> Any:
            return context

    class IntentRepository:
        reads = 0

        def __init__(self, session: Any) -> None:
            self.session = session

        def get_classification_for_turn(self, *args: Any) -> Any:
            type(self).reads += 1
            return None if type(self).reads == 1 else winner

        def create_classification_evidence(self, **kwargs: Any) -> Any:
            raise IntegrityError("insert", {}, _IdempotencyOrig())

    monkeypatch.setattr(runtime, "AssistantRepository", AssistantRepository)
    monkeypatch.setattr(runtime, "ConversationIntentModelRepository", IntentRepository)
    monkeypatch.setattr(runtime, "resolve_effective_intent_model", lambda *args, **kwargs: effective_model)
    monkeypatch.setattr(
        runtime,
        "classify_intent",
        lambda **kwargs: _classification_result(effective_model),
    )

    resolved = runtime.resolve_conversation_intent_classification(
        _Session(),
        organization_id=context.organization_id,
        conversation_turn_id=context.conversation_turn_id,
    )

    assert resolved is winner
    assert IntentRepository.reads == 2


def test_unrelated_classification_integrity_error_propagates(monkeypatch: Any) -> None:
    context = _context()
    effective_model = _effective_model(context.organization_id)

    class OtherDiag:
        constraint_name = "unrelated_constraint"

    class OtherOrig(Exception):
        diag = OtherDiag()

    class AssistantRepository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_scoped_conversation_context_package(self, **kwargs: Any) -> Any:
            return context

    class IntentRepository:
        def __init__(self, session: Any) -> None:
            self.session = session

        def get_classification_for_turn(self, *args: Any) -> None:
            return None

        def create_classification_evidence(self, **kwargs: Any) -> Any:
            raise IntegrityError("insert", {}, OtherOrig())

    monkeypatch.setattr(runtime, "AssistantRepository", AssistantRepository)
    monkeypatch.setattr(runtime, "ConversationIntentModelRepository", IntentRepository)
    monkeypatch.setattr(runtime, "resolve_effective_intent_model", lambda *args, **kwargs: effective_model)
    monkeypatch.setattr(
        runtime,
        "classify_intent",
        lambda **kwargs: _classification_result(effective_model),
    )

    with pytest.raises(IntegrityError):
        runtime.resolve_conversation_intent_classification(
            _Session(),
            organization_id=context.organization_id,
            conversation_turn_id=context.conversation_turn_id,
        )


def test_structured_classification_hash_changes_with_semantic_fields() -> None:
    context = _context()
    effective_model = _effective_model(context.organization_id)
    baseline = _classification_result(effective_model)

    def digest(result: IntentClassificationResult) -> str:
        return runtime._canonical_hash(
            runtime._classification_hash_payload(
                organization_id=context.organization_id,
                context_package=context,
                result=result,
            )
        )

    baseline_hash = digest(baseline)
    baseline_payload = runtime._classification_hash_payload(
        organization_id=context.organization_id,
        context_package=context,
        result=baseline,
    )
    same = IntentClassificationResult(**vars(baseline))
    changed_intent = IntentClassificationResult(**{**vars(baseline), "intent": "knowledge_query"})
    changed_sub_intent = IntentClassificationResult(**{**vars(baseline), "sub_intent": "other-structured-sub-intent"})
    changed_parameters = IntentClassificationResult(**{**vars(baseline), "intent_parameters": {"structured": False}})

    assert digest(same) == baseline_hash
    assert baseline_payload["intent_model_id"] == str(effective_model.intent_model_id)
    assert digest(changed_intent) != baseline_hash
    assert digest(changed_sub_intent) != baseline_hash
    assert digest(changed_parameters) != baseline_hash
