from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.services import conversation_gateway


class _Repository:
    def __init__(self, conversation, response=None, verification=None) -> None:
        self.conversation = conversation
        self.response = response
        self.verification = verification

    def get_conversation(self, conversation_id):
        return self.conversation

    def get_assistant_response(self, assistant_response_id):
        return self.response

    def get_citation_verification(self, citation_verification_id):
        return self.verification

    def find_conversation_turn_by_assistant_response(self, **kwargs):
        return None


def test_assistant_turn_gateway_uses_persisted_assistant_execution_gate(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        assistant_id=uuid.uuid4(),
        assistant_session_id=uuid.uuid4(),
    )
    repository = _Repository(conversation)
    monkeypatch.setattr(conversation_gateway, "AssistantRepository", lambda db: repository)
    gate = SimpleNamespace(ready=True, blocking_issues=())
    monkeypatch.setattr(
        conversation_gateway,
        "evaluate_assistant_execution_conversation_gate_v1",
        lambda *args, **kwargs: gate,
    )
    monkeypatch.setattr(
        conversation_gateway,
        "serialize_assistant_execution_conversation_gate_v1",
        lambda value: {"ready": True, "authority": "postgresql", "contract": "AssistantExecutionEvidenceV1"},
    )

    result = conversation_gateway.validate_conversation_turn_creation(
        MagicMock(spec=Session),
        conversation_id=str(conversation.conversation_id),
        turn_role="assistant",
        assistant_run_id=str(uuid.uuid4()),
        organization_id=organization_id,
    )

    assert result["conversation_turn_gateway_ready"] is True
    assert result["assistant_execution_evidence_gate"]["authority"] == "postgresql"
    assert result["blocking_issues"] == []


def test_response_attachment_rejects_missing_persisted_assistant_run_lineage(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
    )
    response = SimpleNamespace(
        assistant_response_id=uuid.uuid4(),
        citation_verification_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
    )
    verification = SimpleNamespace(assistant_runtime_id=None)
    repository = _Repository(conversation, response=response, verification=verification)
    monkeypatch.setattr(conversation_gateway, "AssistantRepository", lambda db: repository)

    result = conversation_gateway.validate_assistant_response_attachment(
        MagicMock(spec=Session),
        conversation_id=str(conversation.conversation_id),
        assistant_response_id=str(response.assistant_response_id),
    )

    assert result["conversation_response_gateway_ready"] is False
    assert result["blocking_issues"][0]["code"] == "assistant_execution_lineage_missing"
