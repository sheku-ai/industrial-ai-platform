"""Community intent classification engine.

SetFit is the default classifier. Runtime classification remains optional from a
platform dependency perspective: when the configured local model artifact is
unavailable, callers receive no classification and must apply the persisted
technical fallback policy. No alternate semantic classifier is executed here.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.services.community_intent_model_artifact import (
    COMMUNITY_INTENT_PROVIDER,
    prepare_e5_classification_text,
)
from app.services.conversation_intent_model_runtime import EffectiveIntentModel


COMMUNITY_INTENT_ENGINE_VERSION = "community-intent-engine.v1"
SUPPORTED_INTENTS = frozenset(
    {
        "knowledge_query",
        "contextual_follow_up",
        "new_topic",
        "response_refinement",
        "citation_request",
        "conversation_summary",
        "non_knowledge_interaction",
    }
)


@dataclass(frozen=True, kw_only=True)
class IntentClassificationResult:
    intent: str
    sub_intent: str | None
    intent_parameters: dict[str, Any]
    confidence: float
    provider: str
    model_version: str
    intent_model_id: uuid.UUID
    model_family: str
    model_scope_type: str
    artifact_reference: str
    artifact_hash: str
    resolution_method: str

    def __post_init__(self) -> None:
        try:
            canonical_parameters = json.loads(
                json.dumps(
                    dict(self.intent_parameters),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("intent parameters must be JSON serializable") from exc
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("intent classification confidence must be between 0 and 1")
        object.__setattr__(self, "intent_parameters", canonical_parameters)
        object.__setattr__(self, "confidence", confidence)


class IntentModelUnavailableError(RuntimeError):
    """Raised when the configured Community intent model cannot be loaded."""


@lru_cache(maxsize=4)
def _load_setfit_model(model_reference: str, local_files_only: bool) -> Any:
    try:
        from setfit import SetFitModel
    except ImportError as exc:  # pragma: no cover - depends on deployment packaging
        raise IntentModelUnavailableError("SetFit runtime dependency is unavailable") from exc

    try:
        return SetFitModel.from_pretrained(
            model_reference,
            local_files_only=local_files_only,
            device="cpu",
        )
    except Exception as exc:  # pragma: no cover - provider-specific load failures
        raise IntentModelUnavailableError(
            f"configured Community intent model is unavailable: {model_reference}"
        ) from exc


def _prediction_with_confidence(model: Any, *, text: str) -> tuple[str, float] | None:
    labels = [str(label) for label in list(getattr(model, "labels", None) or [])]
    if not labels:
        return None
    probabilities = model.predict_proba(text, as_numpy=True)
    if hasattr(probabilities, "tolist"):
        probabilities = probabilities.tolist()
    if (
        isinstance(probabilities, (list, tuple))
        and len(probabilities) == 1
        and isinstance(probabilities[0], (list, tuple))
    ):
        probabilities = probabilities[0]
    try:
        values = [float(value) for value in probabilities]
    except (TypeError, ValueError):
        return None
    if len(values) != len(labels) or not values or not all(math.isfinite(value) for value in values):
        return None
    prediction_index = max(range(len(values)), key=values.__getitem__)
    return labels[prediction_index], max(0.0, min(1.0, values[prediction_index]))


def classify_intent(
    *,
    current_user_message: str,
    effective_model: EffectiveIntentModel,
) -> IntentClassificationResult | None:
    """Classify one message with the PostgreSQL-resolved SetFit model.

    Returning ``None`` means classification evidence was not produced. The
    caller remains responsible for applying its persisted fallback policy.
    """
    message = str(current_user_message or "").strip()
    if not message:
        return None

    if effective_model.provider != COMMUNITY_INTENT_PROVIDER:
        return None
    model_reference = str(effective_model.artifact_reference or "").strip()
    if not model_reference or not effective_model.artifact_hash:
        return None

    try:
        model = _load_setfit_model(model_reference, True)
    except IntentModelUnavailableError:
        return None

    prepared_message = prepare_e5_classification_text(message)
    try:
        prediction_result = _prediction_with_confidence(model, text=prepared_message)
    except Exception:  # pragma: no cover - provider-specific inference failures
        return None
    if prediction_result is None:
        return None
    prediction, confidence = prediction_result
    prediction = prediction.strip()
    if prediction not in SUPPORTED_INTENTS:
        return None
    return IntentClassificationResult(
        intent=prediction,
        sub_intent=None,
        intent_parameters={},
        confidence=confidence,
        provider=effective_model.provider,
        model_version=effective_model.model_version,
        intent_model_id=effective_model.intent_model_id,
        model_family=effective_model.model_family,
        model_scope_type=effective_model.scope_type,
        artifact_reference=effective_model.artifact_reference,
        artifact_hash=effective_model.artifact_hash,
        resolution_method="community.setfit.classification",
    )
