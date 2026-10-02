from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.contracts.runtime_execution import RuntimeExecutionRequest
from app.orchestration import (
    DisabledRuntimeExecutionOrchestrator,
    ExecutionState,
    FallbackReason,
    OrchestrationPolicy,
    RuntimeExecutionOrchestrator,
)


def make_request(*, generation_allowed: bool = True, resolved_answer_mode: str = "assisted") -> RuntimeExecutionRequest:
    return RuntimeExecutionRequest(
        request_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        requested_answer_mode="assisted",
        resolved_answer_mode=resolved_answer_mode,
        runtime_profile_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        prompt_id=uuid.uuid4(),
        guardrail_id=uuid.uuid4(),
        generation_allowed=generation_allowed,
        context=("evidence",),
        citations=({"source": "smoke"},),
    )


def assert_safe_result(result, expected_reason: FallbackReason) -> None:
    assert result.fallback_used is True
    assert result.fallback_reason == expected_reason.value
    assert result.answer_generated is False
    assert result.execution_attempted is False
    assert result.metadata["provider_execution_performed"] is False
    assert result.metadata["secret_resolution_performed"] is False
    assert result.metadata["network_call_performed"] is False
    assert result.metadata["generation_performed"] is False
    assert result.metadata["attempt_count"] == 0


def main() -> None:
    orchestrator = DisabledRuntimeExecutionOrchestrator()
    assert isinstance(orchestrator, RuntimeExecutionOrchestrator)

    disabled = orchestrator.execute(
        make_request(),
        policy=OrchestrationPolicy(),
    )
    assert_safe_result(disabled, FallbackReason.EXECUTION_NOT_ENABLED)
    assert disabled.status == ExecutionState.FALLBACK_COMPLETED.value

    generation_blocked = orchestrator.execute(
        make_request(generation_allowed=False),
        policy=OrchestrationPolicy(execution_enabled=True),
    )
    assert_safe_result(generation_blocked, FallbackReason.GENERATION_NOT_ALLOWED)

    provider_disabled = orchestrator.execute(
        make_request(),
        policy=OrchestrationPolicy(execution_enabled=True),
    )
    assert_safe_result(provider_disabled, FallbackReason.PROVIDER_EXECUTION_NOT_ENABLED)

    provider_not_ready = orchestrator.execute(
        make_request(),
        policy=OrchestrationPolicy(
            execution_enabled=True,
            provider_execution_enabled=True,
        ),
    )
    assert_safe_result(provider_not_ready, FallbackReason.PROVIDER_NOT_READY)

    print(
        {
            "status": "passed",
            "orchestrator_contract": True,
            "provider_execution_performed": False,
            "secret_resolution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
