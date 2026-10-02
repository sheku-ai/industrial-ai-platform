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
    IdempotencyStatus,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    build_idempotency_key,
)


def make_request(*, request_id: uuid.UUID, parameters: dict | None = None) -> RuntimeExecutionRequest:
    return RuntimeExecutionRequest(
        request_id=request_id,
        organization_id=uuid.uuid4(),
        requested_answer_mode="assisted",
        resolved_answer_mode="assisted",
        runtime_profile_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        prompt_id=uuid.uuid4(),
        guardrail_id=uuid.uuid4(),
        generation_allowed=True,
        context=("context-a", "context-b"),
        variables={"question": "status"},
        parameters=parameters or {"temperature": 0.1, "max_tokens": 128},
    )


def clone_request(source: RuntimeExecutionRequest, *, parameters: dict | None = None) -> RuntimeExecutionRequest:
    return RuntimeExecutionRequest(
        request_id=source.request_id,
        organization_id=source.organization_id,
        requested_answer_mode=source.requested_answer_mode,
        resolved_answer_mode=source.resolved_answer_mode,
        runtime_profile_id=source.runtime_profile_id,
        provider_id=source.provider_id,
        model_id=source.model_id,
        prompt_id=source.prompt_id,
        guardrail_id=source.guardrail_id,
        generation_allowed=source.generation_allowed,
        context=source.context,
        citations=source.citations,
        variables=source.variables,
        parameters=parameters if parameters is not None else source.parameters,
        timeout_ms=source.timeout_ms,
        metadata=source.metadata,
    )


def main() -> None:
    request = make_request(request_id=uuid.uuid4())
    equivalent = clone_request(request)

    key_a = build_idempotency_key(request, rendered_prompt_hash="prompt-hash")
    key_b = build_idempotency_key(equivalent, rendered_prompt_hash="prompt-hash")
    assert key_a == key_b

    reordered = clone_request(
        request,
        parameters={"max_tokens": 128, "temperature": 0.1},
    )
    key_reordered = build_idempotency_key(reordered, rendered_prompt_hash="prompt-hash")
    assert key_reordered == key_a

    changed = clone_request(request, parameters={"temperature": 0.2, "max_tokens": 128})
    changed_key = build_idempotency_key(changed, rendered_prompt_hash="prompt-hash")
    assert changed_key.value != key_a.value

    store = InMemoryIdempotencyStore()
    assert isinstance(store, IdempotencyStore)

    first = store.claim(key_a)
    assert first.acquired is True
    assert first.record.status == IdempotencyStatus.ACQUIRED

    duplicate = store.claim(key_a)
    assert duplicate.acquired is False
    assert duplicate.record == first.record

    completed = store.complete(key_a, result_reference="runtime-result:1")
    assert completed.status == IdempotencyStatus.COMPLETED
    assert completed.result_reference == "runtime-result:1"

    replay = store.claim(key_a)
    assert replay.acquired is False
    assert replay.record.status == IdempotencyStatus.COMPLETED
    assert replay.record.result_reference == "runtime-result:1"

    failure_key = build_idempotency_key(
        make_request(request_id=uuid.uuid4()),
        rendered_prompt_hash="prompt-hash",
    )
    assert store.claim(failure_key).acquired is True
    failed = store.fail(failure_key, failure_code="provider_timeout")
    assert failed.status == IdempotencyStatus.FAILED
    assert failed.failure_code == "provider_timeout"

    print(
        {
            "status": "passed",
            "deterministic_key": True,
            "mapping_order_independent": True,
            "execution_input_sensitive": True,
            "duplicate_claim_blocked": True,
            "completed_result_replayable": True,
            "failure_recorded": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
