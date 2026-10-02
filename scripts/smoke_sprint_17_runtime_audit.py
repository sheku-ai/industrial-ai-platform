from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    ExecutionState,
    FallbackReason,
    InMemoryRuntimeAuditSink,
    RuntimeAuditAction,
    RuntimeAuditSink,
    create_runtime_audit_event,
)


def assert_raises(expected, fn) -> None:
    try:
        fn()
    except expected:
        return
    raise AssertionError(f"{expected.__name__} was not raised")


def main() -> None:
    request_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    provider_id = uuid.uuid4()
    sink = InMemoryRuntimeAuditSink()
    assert isinstance(sink, RuntimeAuditSink)

    event = create_runtime_audit_event(
        action=RuntimeAuditAction.EXECUTION_FALLBACK_COMPLETED,
        request_id=request_id,
        organization_id=organization_id,
        execution_state=ExecutionState.FALLBACK_COMPLETED,
        previous_state=ExecutionState.VALIDATED,
        provider_id=provider_id,
        fallback_reason=FallbackReason.PROVIDER_EXECUTION_NOT_ENABLED,
        idempotency_key="raw-idempotency-key",
        rendered_prompt="sensitive rendered prompt",
        metadata={"decision": "fallback"},
    )
    sink.emit(event)

    stored = sink.events()[0]
    assert stored.request_id == request_id
    assert stored.organization_id == organization_id
    assert stored.idempotency_key_hash is not None
    assert stored.prompt_hash is not None
    assert stored.idempotency_key_hash != "raw-idempotency-key"
    assert stored.prompt_hash != "sensitive rendered prompt"
    assert "sensitive rendered prompt" not in str(stored)
    assert stored.answer_generated is False

    assert_raises(
        ValueError,
        lambda: create_runtime_audit_event(
            action=RuntimeAuditAction.EXECUTION_RECEIVED,
            request_id=request_id,
            organization_id=organization_id,
            execution_state=ExecutionState.RECEIVED,
            metadata={"api_key": "forbidden"},
        ),
    )

    print({
        "status": "passed",
        "audit_contract": True,
        "organization_scoped": True,
        "prompt_redacted_by_hash": True,
        "idempotency_key_redacted_by_hash": True,
        "sensitive_metadata_blocked": True,
        "non_execution_decisions_auditable": True,
        "provider_execution_performed": False,
        "network_call_performed": False,
        "generation_performed": False,
    })


if __name__ == "__main__":
    main()
