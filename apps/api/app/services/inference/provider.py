from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

DETERMINISTIC_ASSISTED_PROVIDER_REF = "deterministic-grounded"
DETERMINISTIC_FAILURE_PROVIDER_REF = "deterministic-failure"
DETERMINISTIC_TIMEOUT_PROVIDER_REF = "deterministic-timeout"


@dataclass(frozen=True)
class InferenceRequest:
    """Generic provider request for grounded assisted answers.

    The request intentionally carries generic references instead of provider-specific
    model names or prompt policies. Provider implementations must remain outside
    FastAPI route handlers.
    """

    provider_ref: str | None
    model_ref: str | None
    prompt_ref: str | None
    guardrail_ref: str | None
    query_text: str
    context: tuple[dict[str, Any], ...] = ()
    citations: tuple[dict[str, Any], ...] = ()
    timeout_ms: int = 30_000
    runtime_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceResult:
    """Provider result normalized for the answer runtime."""

    success: bool
    generated_text: str | None = None
    provider_ref: str | None = None
    model_ref: str | None = None
    prompt_ref: str | None = None
    guardrail_ref: str | None = None
    latency_ms: int | None = None
    usage_metadata: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    provider_adapter: str = "disabled_provider_v1"

    def as_metrics(self) -> dict[str, Any]:
        return {
            "inference_provider_adapter": self.provider_adapter,
            "inference_success": self.success,
            "inference_error_code": self.error_code,
            "inference_latency_ms": self.latency_ms,
            "provider_ref": self.provider_ref,
            "model_ref": self.model_ref,
            "prompt_ref": self.prompt_ref,
            "guardrail_ref": self.guardrail_ref,
            **self.runtime_metadata,
        }


class InferenceProvider(Protocol):
    """Replaceable inference provider boundary."""

    provider_adapter: str

    def generate(self, request: InferenceRequest) -> InferenceResult:
        """Generate a grounded answer or return a normalized failure."""


class DisabledInferenceProvider:
    """Safe default provider used when inference is not configured."""

    provider_adapter = "disabled_provider_v1"

    def generate(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(
            success=False,
            provider_ref=request.provider_ref,
            model_ref=request.model_ref,
            prompt_ref=request.prompt_ref,
            guardrail_ref=request.guardrail_ref,
            runtime_metadata=request.runtime_options,
            error_code="provider_not_configured",
            error_message="No inference provider is configured for assisted answer mode.",
            provider_adapter=self.provider_adapter,
        )


class DeterministicGroundedInferenceProvider:
    """Deterministic assisted-answer provider for runtime validation."""

    provider_adapter = "deterministic_grounded_provider_v1"

    def generate(self, request: InferenceRequest) -> InferenceResult:
        if not request.context or not request.citations:
            return InferenceResult(
                success=False,
                provider_ref=request.provider_ref,
                model_ref=request.model_ref,
                prompt_ref=request.prompt_ref,
                guardrail_ref=request.guardrail_ref,
                runtime_metadata=request.runtime_options,
                error_code="no_evidence_in_context",
                error_message="Assisted answer requires context and citations.",
                provider_adapter=self.provider_adapter,
            )

        evidence_lines: list[str] = []
        for item in request.context[:3]:
            citation_key = item.get("citation_key") or "citation"
            text = " ".join(str(item.get("text") or "").split())
            if len(text) > 220:
                text = f"{text[:217]}..."
            evidence_lines.append(f"- [{citation_key}] {text}")

        generated_text = "\n".join(
            [
                "Assisted answer based only on retrieved evidence:",
                *evidence_lines,
            ]
        )

        return InferenceResult(
            success=True,
            generated_text=generated_text,
            provider_ref=request.provider_ref,
            model_ref=request.model_ref,
            prompt_ref=request.prompt_ref,
            guardrail_ref=request.guardrail_ref,
            latency_ms=0,
            usage_metadata={"context_items_used": len(evidence_lines)},
            runtime_metadata={
                **request.runtime_options,
                "assisted_generation_strategy": "deterministic_grounded_context_v1",
                "assisted_context_items_used": len(evidence_lines),
            },
            provider_adapter=self.provider_adapter,
        )


class DeterministicFailureInferenceProvider:
    """Deterministic provider failure for fallback validation."""

    provider_adapter = "deterministic_failure_provider_v1"

    def generate(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(
            success=False,
            provider_ref=request.provider_ref,
            model_ref=request.model_ref,
            prompt_ref=request.prompt_ref,
            guardrail_ref=request.guardrail_ref,
            runtime_metadata=request.runtime_options,
            error_code="provider_failed",
            error_message="Deterministic provider failure requested for fallback validation.",
            provider_adapter=self.provider_adapter,
        )


class DeterministicTimeoutInferenceProvider:
    """Deterministic timeout result for fallback validation.

    This class does not sleep. It returns a normalized timeout failure so smoke
    validation remains fast and deterministic.
    """

    provider_adapter = "deterministic_timeout_provider_v1"

    def generate(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(
            success=False,
            provider_ref=request.provider_ref,
            model_ref=request.model_ref,
            prompt_ref=request.prompt_ref,
            guardrail_ref=request.guardrail_ref,
            latency_ms=request.timeout_ms,
            runtime_metadata=request.runtime_options,
            error_code="provider_timeout",
            error_message="Deterministic provider timeout requested for fallback validation.",
            provider_adapter=self.provider_adapter,
        )


def resolve_inference_provider(provider_ref: str | None = None) -> InferenceProvider:
    """Resolve an inference provider implementation.

    The default remains disabled. Deterministic providers are explicit runtime
    validation adapters, not product AI providers.
    """

    if provider_ref == DETERMINISTIC_ASSISTED_PROVIDER_REF:
        return DeterministicGroundedInferenceProvider()
    if provider_ref == DETERMINISTIC_FAILURE_PROVIDER_REF:
        return DeterministicFailureInferenceProvider()
    if provider_ref == DETERMINISTIC_TIMEOUT_PROVIDER_REF:
        return DeterministicTimeoutInferenceProvider()
    return DisabledInferenceProvider()
