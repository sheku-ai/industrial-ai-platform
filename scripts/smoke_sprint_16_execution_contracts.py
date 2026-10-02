#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.contracts.runtime_execution import (  # noqa: E402
    GuardrailEvaluationRequest,
    GuardrailEvaluationResult,
    InferenceRequest,
    InferenceResponse,
    PromptRenderRequest,
    PromptRenderResult,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)


class SmokeFailure(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke() -> dict[str, object]:
    contract_types = (
        InferenceRequest,
        InferenceResponse,
        ProviderExecutionRequest,
        ProviderExecutionResult,
        PromptRenderRequest,
        PromptRenderResult,
        GuardrailEvaluationRequest,
        GuardrailEvaluationResult,
        RuntimeExecutionRequest,
        RuntimeExecutionResult,
    )
    check(all(dataclasses.is_dataclass(item) for item in contract_types), "All execution contracts must be dataclasses")
    check(all(item.__dataclass_params__.frozen for item in contract_types), "All execution contracts must be frozen")

    request_id = uuid.uuid4()
    request = RuntimeExecutionRequest(
        request_id=request_id,
        organization_id=None,
        requested_answer_mode="assisted",
        resolved_answer_mode="assisted",
        runtime_profile_id=None,
        provider_id=None,
        model_id=None,
        prompt_id=None,
        guardrail_id=None,
        generation_allowed=False,
        context=("context",),
        citations=({"source": "reference"},),
    )
    result = RuntimeExecutionResult(
        request_id=request_id,
        status="fallback",
        resolved_answer_mode="extractive",
        answer_generated=False,
        execution_attempted=False,
        fallback_used=True,
        fallback_reason="execution_not_allowed",
    )

    check(request.generation_allowed is False, "No-execution request must be representable")
    check(result.execution_attempted is False, "No-execution result must be representable")
    check(result.answer_generated is False, "No-generation result must be representable")
    check(result.fallback_used is True, "Fallback result must be representable")

    return {
        "status": "passed",
        "sprint": "16.1",
        "validation": "execution_contracts",
        "contract_count": len(contract_types),
        "immutable": True,
        "provider_specific_types": False,
        "provider_execution_performed": False,
        "generation_performed": False,
    }


def main() -> int:
    try:
        result = run_smoke()
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
