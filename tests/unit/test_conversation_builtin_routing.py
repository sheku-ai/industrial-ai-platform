from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import conversation_intent_engine
from app.services.conversation_intent_model_runtime import EffectiveIntentModel


class _Model:
    def __init__(self, prediction: str = "knowledge_query") -> None:
        self.labels = [prediction, "response_refinement"]
        self.proba_calls: list[str] = []

    def predict_proba(self, text: str, *, as_numpy: bool):
        assert as_numpy is True
        self.proba_calls.append(text)
        return [0.91, 0.09]


def _effective_model(*, artifact_reference: str = "runtime/intent-models/community-v1"):
    return EffectiveIntentModel(
        intent_model_id=uuid.uuid4(),
        model_family="conversation_intent",
        provider="community.setfit",
        model_version="community-intent-v1",
        scope_type="community",
        organization_id=None,
        organization_node_id=None,
        artifact_reference=artifact_reference,
        artifact_hash="a" * 64,
    )


def test_setfit_is_the_single_community_intent_provider(monkeypatch) -> None:
    model = _Model()
    effective_model = _effective_model()
    loaded: dict[str, object] = {}

    def load_model(model_reference: str, local_files_only: bool):
        loaded["model_reference"] = model_reference
        loaded["local_files_only"] = local_files_only
        return model

    monkeypatch.setattr(conversation_intent_engine, "_load_setfit_model", load_model)

    result = conversation_intent_engine.classify_intent(
        current_user_message="What is the approval policy?",
        effective_model=effective_model,
    )

    assert result is not None
    assert result.intent == "knowledge_query"
    assert result.confidence == 0.91
    assert result.provider == "community.setfit"
    assert result.model_version == effective_model.model_version
    assert result.intent_model_id == effective_model.intent_model_id
    assert result.model_family == effective_model.model_family
    assert result.model_scope_type == effective_model.scope_type
    assert result.artifact_reference == effective_model.artifact_reference
    assert result.artifact_hash == effective_model.artifact_hash
    assert result.sub_intent is None
    assert result.intent_parameters == {}
    assert result.resolution_method == "community.setfit.classification"
    assert loaded == {
        "model_reference": "runtime/intent-models/community-v1",
        "local_files_only": True,
    }
    assert model.proba_calls == ["query: What is the approval policy?"]


def test_setfit_loader_is_offline_and_cpu_only(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSetFitModel:
        @classmethod
        def from_pretrained(cls, model_reference: str, **kwargs):
            captured["model_reference"] = model_reference
            captured.update(kwargs)
            return object()

    monkeypatch.setitem(
        __import__("sys").modules,
        "setfit",
        SimpleNamespace(SetFitModel=FakeSetFitModel),
    )
    conversation_intent_engine._load_setfit_model.cache_clear()
    try:
        conversation_intent_engine._load_setfit_model(
            "runtime/intent-models/community-intent-v1",
            True,
        )
    finally:
        conversation_intent_engine._load_setfit_model.cache_clear()

    assert captured == {
        "model_reference": "runtime/intent-models/community-intent-v1",
        "local_files_only": True,
        "device": "cpu",
    }


def test_missing_model_artifact_produces_no_classification() -> None:
    result = conversation_intent_engine.classify_intent(
        current_user_message="What is the approval policy?",
        effective_model=_effective_model(artifact_reference=""),
    )

    assert result is None


def test_model_unavailable_produces_no_classification_and_no_secondary_classifier(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise conversation_intent_engine.IntentModelUnavailableError("missing model")

    monkeypatch.setattr(conversation_intent_engine, "_load_setfit_model", unavailable)

    result = conversation_intent_engine.classify_intent(
        current_user_message="Translate the previous answer",
        effective_model=_effective_model(),
    )

    assert result is None


def test_setfit_inference_failure_produces_no_classification(monkeypatch) -> None:
    class FailingModel:
        labels = ["knowledge_query"]

        def predict_proba(self, text: str, *, as_numpy: bool):
            raise RuntimeError("inference unavailable")

    monkeypatch.setattr(
        conversation_intent_engine,
        "_load_setfit_model",
        lambda *args, **kwargs: FailingModel(),
    )

    result = conversation_intent_engine.classify_intent(
        current_user_message="What is the approval policy?",
        effective_model=_effective_model(),
    )

    assert result is None


def test_unsupported_model_label_is_rejected(monkeypatch) -> None:
    model = _Model(prediction="unsupported_intent")
    monkeypatch.setattr(conversation_intent_engine, "_load_setfit_model", lambda *args, **kwargs: model)

    result = conversation_intent_engine.classify_intent(
        current_user_message="Do something unsupported",
        effective_model=_effective_model(),
    )

    assert result is None
