from __future__ import annotations

from unittest.mock import MagicMock

from app.services.product_acceptance.gateway import HttpResult
from app.services.product_acceptance.idempotency_evidence_runtime import (
    IdempotencyEvidenceAwareLocalProductAcceptanceRuntime,
)
from app.services.product_acceptance.runtime import RuntimeOptions

ORG_ID = "11111111-1111-1111-1111-111111111111"
ARTIFACT_ID = "22222222-2222-2222-2222-222222222222"
DOCUMENT_ID = "33333333-3333-3333-3333-333333333333"
VERSION_ID = "44444444-4444-4444-4444-444444444444"
PROCESSING_ID = "55555555-5555-5555-5555-555555555555"
PUBLICATION_EVIDENCE_ID = "66666666-6666-6666-6666-666666666666"
KNOWLEDGE_DOCUMENT_ID = "77777777-7777-7777-7777-777777777777"
ASSISTANT_ID = "88888888-8888-8888-8888-888888888888"
CONVERSATION_ID = "99999999-9999-9999-9999-999999999999"
RUN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TURN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RESPONSE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _runtime() -> IdempotencyEvidenceAwareLocalProductAcceptanceRuntime:
    runtime = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime(
        RuntimeOptions(api_base_url="http://127.0.0.1:8000/api")
    )
    runtime.state.resources.update(
        {
            "organization": {"id": ORG_ID},
            "artifact": {"id": ARTIFACT_ID},
            "assistant": {"id": ASSISTANT_ID},
        }
    )
    return runtime


def _document_evidence() -> dict:
    return {
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "artifact_id": ARTIFACT_ID,
        "document_record_id": DOCUMENT_ID,
        "document_version_id": VERSION_ID,
        "processing": {
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "processing_evidence_id": PROCESSING_ID,
            "ready": True,
        },
        "knowledge_publication": {
            "authority": "postgresql",
            "ready": True,
            "evidence": {
                "contract": "KnowledgePublicationEvidenceV1",
                "evidence_id": PUBLICATION_EVIDENCE_ID,
            },
        },
        "knowledge_index": {
            "authority": "postgresql",
            "ready": True,
            "evidence": {
                "contract": "KnowledgeIndexEvidenceV1",
                "knowledge_document_id": KNOWLEDGE_DOCUMENT_ID,
                "publication_id": "publication-1",
            },
        },
    }


def _conversation_evidence() -> dict:
    return {
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "conversation_id": CONVERSATION_ID,
        "assistant_run_id": RUN_ID,
        "ready": True,
        "assistant_execution": {
            "contract": "AssistantExecutionEvidenceV1",
            "assistant_run_id": RUN_ID,
            "assistant_id": ASSISTANT_ID,
            "authority": "postgresql",
        },
        "conversation_event": {
            "contract": "ConversationEventEvidenceV1",
            "conversation_turn_id": TURN_ID,
            "conversation_id": CONVERSATION_ID,
            "assistant_run_id": RUN_ID,
            "assistant_id": ASSISTANT_ID,
            "assistant_response_id": RESPONSE_ID,
            "turn_role": "assistant",
            "turn_status": "completed",
            "output_present": True,
        },
    }


def test_processing_idempotency_requires_same_persisted_evidence_identity() -> None:
    before = _document_evidence()
    after = _document_evidence()

    details = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime._processing_idempotency_details(before, after)

    assert details["idempotent"] is True
    assert details["same_persisted_evidence_reused"] is True

    after["processing"]["processing_evidence_id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    changed = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime._processing_idempotency_details(before, after)
    assert changed["idempotent"] is False
    assert changed["same_persisted_evidence_reused"] is False


def test_knowledge_idempotency_requires_publication_and_index_identity_reuse() -> None:
    before = _document_evidence()
    after = _document_evidence()

    details = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime._knowledge_idempotency_details(before, after)

    assert details["idempotent"] is True
    assert details["same_publication_evidence_reused"] is True
    assert details["same_knowledge_document_reused"] is True

    after["knowledge_index"]["evidence"]["knowledge_document_id"] = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    changed = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime._knowledge_idempotency_details(before, after)
    assert changed["idempotent"] is False
    assert changed["same_knowledge_document_reused"] is False


def test_assistant_response_idempotency_requires_real_replay_and_same_persisted_lineage() -> None:
    runtime = _runtime()
    request_id = runtime._chat_request_id(ASSISTANT_ID)
    conversation_before = {
        "conversation_id": CONVERSATION_ID,
        "assistant_run_id": RUN_ID,
        "assistant_response_id": RESPONSE_ID,
        "request_id": request_id,
        "assistant_conversation_evidence": _conversation_evidence(),
    }
    runtime.http.post = MagicMock(
        return_value=HttpResult(
            ok=True,
            status_code=200,
            method="POST",
            path="/assistants/chat",
            data={
                "conversation_id": CONVERSATION_ID,
                "assistant_run_id": RUN_ID,
                "assistant_response_id": RESPONSE_ID,
                "idempotent_replay": True,
                "chat_completed": True,
            },
        )
    )
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            ok=True,
            status_code=200,
            method="GET",
            path="/product-acceptance/runtime-evidence/assistant-conversation",
            data=_conversation_evidence(),
        )
    )

    details = runtime._replay_chat(conversation_before)

    assert details["idempotent"] is True
    assert details["idempotent_replay"] is True
    assert details["same_conversation_reused"] is True
    assert details["same_assistant_run_reused"] is True
    assert details["same_conversation_event_reused"] is True
    assert details["same_assistant_response_reused"] is True
    replay_payload = runtime.http.post.call_args.args[1]
    assert replay_payload["request_id"] == request_id


def test_assistant_response_idempotency_rejects_new_run_despite_successful_http_replay() -> None:
    runtime = _runtime()
    request_id = runtime._chat_request_id(ASSISTANT_ID)
    conversation_before = {
        "conversation_id": CONVERSATION_ID,
        "assistant_run_id": RUN_ID,
        "assistant_response_id": RESPONSE_ID,
        "request_id": request_id,
        "assistant_conversation_evidence": _conversation_evidence(),
    }
    new_run_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    replay_evidence = _conversation_evidence()
    replay_evidence["assistant_run_id"] = new_run_id
    replay_evidence["assistant_execution"]["assistant_run_id"] = new_run_id
    replay_evidence["conversation_event"]["assistant_run_id"] = new_run_id
    runtime.http.post = MagicMock(
        return_value=HttpResult(
            ok=True,
            status_code=200,
            method="POST",
            path="/assistants/chat",
            data={
                "conversation_id": CONVERSATION_ID,
                "assistant_run_id": new_run_id,
                "assistant_response_id": RESPONSE_ID,
                "idempotent_replay": True,
            },
        )
    )
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            ok=True,
            status_code=200,
            method="GET",
            path="/product-acceptance/runtime-evidence/assistant-conversation",
            data=replay_evidence,
        )
    )

    details = runtime._replay_chat(conversation_before)

    assert details["idempotent"] is False
    assert details["same_assistant_run_reused"] is False
