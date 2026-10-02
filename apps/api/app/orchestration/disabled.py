from __future__ import annotations

from app.contracts.runtime_execution import RuntimeExecutionRequest, RuntimeExecutionResult
from app.orchestration.base import (
    CancellationBoundary,
    ExecutionState,
    FailureCategory,
    FallbackReason,
    NeverCancelled,
    OrchestrationPolicy,
)


class DisabledRuntimeExecutionOrchestrator:
    """Safe orchestrator used while provider execution remains disabled.

    The class validates hard execution barriers and always produces a
    deterministic non-generative result. It performs no secret resolution,
    provider health check, adapter invocation or network call.
    """

    def execute(
        self,
        request: RuntimeExecutionRequest,
        *,
        policy: OrchestrationPolicy,
        cancellation: CancellationBoundary | None = None,
    ) -> RuntimeExecutionResult:
        cancellation_boundary = cancellation or NeverCancelled()

        if cancellation_boundary.is_cancelled():
            return self._fallback(
                request,
                state=ExecutionState.CANCELLED,
                reason=FallbackReason.EXECUTION_CANCELLED,
                failure_category=FailureCategory.CANCELLED,
            )

        if not policy.execution_enabled:
            return self._fallback(
                request,
                state=ExecutionState.FALLBACK_COMPLETED,
                reason=FallbackReason.EXECUTION_NOT_ENABLED,
            )

        if not request.generation_allowed:
            return self._fallback(
                request,
                state=ExecutionState.FALLBACK_COMPLETED,
                reason=FallbackReason.GENERATION_NOT_ALLOWED,
                failure_category=FailureCategory.ELIGIBILITY_REJECTED,
            )

        if request.resolved_answer_mode != "assisted":
            return self._fallback(
                request,
                state=ExecutionState.FALLBACK_COMPLETED,
                reason=FallbackReason.UNSUPPORTED_ANSWER_MODE,
                failure_category=FailureCategory.ELIGIBILITY_REJECTED,
            )

        if not policy.provider_execution_enabled:
            return self._fallback(
                request,
                state=ExecutionState.FALLBACK_COMPLETED,
                reason=FallbackReason.PROVIDER_EXECUTION_NOT_ENABLED,
            )

        return self._fallback(
            request,
            state=ExecutionState.FALLBACK_COMPLETED,
            reason=FallbackReason.PROVIDER_NOT_READY,
            failure_category=FailureCategory.PROVIDER_NOT_READY,
        )

    @staticmethod
    def _fallback(
        request: RuntimeExecutionRequest,
        *,
        state: ExecutionState,
        reason: FallbackReason,
        failure_category: FailureCategory | None = None,
    ) -> RuntimeExecutionResult:
        fallback_mode = "extractive" if request.requested_answer_mode == "assisted" else request.resolved_answer_mode
        metadata = {
            "terminal_state": state.value,
            "failure_category": failure_category.value if failure_category else None,
            "attempt_count": 0,
            "provider_execution_performed": False,
            "secret_resolution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
            "orchestrator": "disabled",
        }

        return RuntimeExecutionResult(
            request_id=request.request_id,
            status=state.value,
            resolved_answer_mode=fallback_mode,
            answer_text=None,
            answer_generated=False,
            execution_attempted=False,
            fallback_used=True,
            fallback_reason=reason.value,
            provider_id=request.provider_id,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
            guardrail_id=request.guardrail_id,
            usage={},
            error_code=failure_category.value if failure_category else None,
            metadata=metadata,
        )
