from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.evidence_runtime import (  # noqa: E402
    EvidenceAwareLocalProductAcceptanceRuntime,
)
from app.services.product_acceptance.gateway import HttpResult  # noqa: E402
from app.services.product_acceptance.runtime import RuntimeOptions  # noqa: E402

ORG_ID = "11111111-1111-1111-1111-111111111111"
ASSISTANT_ID = "22222222-2222-2222-2222-222222222222"
CONVERSATION_ID = "33333333-3333-3333-3333-333333333333"
ASSISTANT_RUN_ID = "44444444-4444-4444-4444-444444444444"
ASSISTANT_RESPONSE_ID = "55555555-5555-5555-5555-555555555555"
TURN_ID = "66666666-6666-6666-6666-666666666666"
SESSION_ID = "77777777-7777-7777-7777-777777777777"


def _runtime() -> EvidenceAwareLocalProductAcceptanceRuntime:
    runtime = EvidenceAwareLocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))
    runtime.state.resources.update(
        {
            "organization": {"id": ORG_ID},
            "assistant": {"id": ASSISTANT_ID, "assistant_id": ASSISTANT_ID},
        }
    )
    return runtime


def _chat_response() -> dict:
    return {
        "conversation_id": CONVERSATION_ID,
        "assistant_run_id": ASSISTANT_RUN_ID,
        "assistant_response_id": ASSISTANT_RESPONSE_ID,
        "chat_completed": True,
        "passed": True,
    }


def _evidence_response() -> dict:
    return {
        "runtime_evidence_schema_version": "1",
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "conversation_id": CONVERSATION_ID,
        "assistant_id": ASSISTANT_ID,
        "assistant_run_id": ASSISTANT_RUN_ID,
        "assistant_response_id": ASSISTANT_RESPONSE_ID,
        "assistant_execution": {
            "contract": "AssistantExecutionEvidenceV1",
            "assistant_run_id": ASSISTANT_RUN_ID,
            "organization_id": ORG_ID,
            "assistant_id": ASSISTANT_ID,
            "assistant_session_id": SESSION_ID,
            "run_status": "completed",
            "execution_state": "completed",
            "authority": "postgresql",
        },
        "conversation_event": {
            "contract": "ConversationEventEvidenceV1",
            "conversation_turn_id": TURN_ID,
            "organization_id": ORG_ID,
            "conversation_id": CONVERSATION_ID,
            "assistant_id": ASSISTANT_ID,
            "assistant_session_id": SESSION_ID,
            "assistant_run_id": ASSISTANT_RUN_ID,
            "assistant_response_id": ASSISTANT_RESPONSE_ID,
            "turn_role": "assistant",
            "turn_status": "completed",
            "output_present": True,
        },
        "ready": True,
        "blocking_issues": [],
    }


def test_conversation_gate_requires_authoritative_assistant_and_event_evidence() -> None:
    runtime = _runtime()
    runtime.http.post = MagicMock(return_value=HttpResult(True, 200, "POST", "/assistants/chat", data=_chat_response()))
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            True,
            200,
            "GET",
            "/product-acceptance/runtime-evidence/assistant-conversation",
            data=_evidence_response(),
        )
    )

    runtime._conversation("conversation")

    gate = runtime.state.gates[-1]
    assert gate["gate_code"] == "conversation_turn_created"
    assert gate["status"] == "PASSED"
    assert gate["details"]["authority"] == "postgresql"
    assert gate["details"]["contract_matches"] is True
    assert gate["details"]["legacy_functional_result_authoritative"] is False


def test_chat_http_success_without_persisted_evidence_fails() -> None:
    runtime = _runtime()
    runtime.http.post = MagicMock(return_value=HttpResult(True, 200, "POST", "/assistants/chat", data=_chat_response()))
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            True,
            200,
            "GET",
            "/product-acceptance/runtime-evidence/assistant-conversation",
            data={
                "authority": "postgresql",
                "organization_id": ORG_ID,
                "conversation_id": CONVERSATION_ID,
                "assistant_run_id": ASSISTANT_RUN_ID,
                "assistant_execution": None,
                "conversation_event": None,
                "ready": False,
                "blocking_issues": [{"code": "conversation_event_evidence_missing"}],
            },
        )
    )

    runtime._conversation("conversation")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "RESOURCE_LINEAGE_INCOMPLETE"
    assert gate["details"]["functional_chat_succeeded"] is True
    assert gate["details"]["legacy_functional_result_authoritative"] is False


def test_conversation_event_from_another_run_fails() -> None:
    runtime = _runtime()
    runtime.http.post = MagicMock(return_value=HttpResult(True, 200, "POST", "/assistants/chat", data=_chat_response()))
    evidence = _evidence_response()
    evidence["conversation_event"] = {
        **evidence["conversation_event"],
        "assistant_run_id": "88888888-8888-8888-8888-888888888888",
    }
    evidence["ready"] = False
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            True,
            200,
            "GET",
            "/product-acceptance/runtime-evidence/assistant-conversation",
            data=evidence,
        )
    )

    runtime._conversation("conversation")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["details"]["contract_matches"] is False


def test_chat_without_assistant_run_id_cannot_pass_conversation_gate() -> None:
    runtime = _runtime()
    response = _chat_response()
    response["assistant_run_id"] = None
    runtime.http.post = MagicMock(return_value=HttpResult(True, 200, "POST", "/assistants/chat", data=response))
    runtime.http.get = MagicMock()

    runtime._conversation("conversation")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["details"]["functional_chat_succeeded"] is True
    runtime.http.get.assert_not_called()
