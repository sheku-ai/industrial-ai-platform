from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import app.services.conversation_gateway as gateway

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps/api/alembic/versions/20260816_999_assistant_response_organization_isolation.py"
)


class _Repository:
    conversation = None
    response = None
    verification = None

    def __init__(self, _db) -> None:
        pass

    def get_conversation(self, _conversation_id):
        return self.conversation

    def get_assistant_response(self, _assistant_response_id):
        return self.response

    def get_citation_verification(self, _citation_verification_id):
        return self.verification

    def find_conversation_turn_by_assistant_response(self, **_kwargs):
        return None


def _issue_codes(result: dict) -> set[str]:
    return {str(item.get("code")) for item in result["blocking_issues"]}


def _configure_valid_assistant_execution_gate(monkeypatch) -> None:
    gate = SimpleNamespace(ready=True, blocking_issues=())
    monkeypatch.setattr(
        gateway,
        "evaluate_assistant_execution_conversation_gate_v1",
        lambda *args, **kwargs: gate,
    )
    monkeypatch.setattr(
        gateway,
        "serialize_assistant_execution_conversation_gate_v1",
        lambda value: {
            "ready": True,
            "authority": "postgresql",
            "contract": "AssistantExecutionEvidenceV1",
        },
    )


def test_attachment_accepts_same_organization_runtime_evidence(monkeypatch) -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    response_id = uuid4()
    citation_verification_id = uuid4()
    assistant_run_id = uuid4()
    _Repository.conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )
    _Repository.response = SimpleNamespace(
        assistant_response_id=response_id,
        citation_verification_id=citation_verification_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )
    _Repository.verification = SimpleNamespace(assistant_runtime_id=assistant_run_id)
    monkeypatch.setattr(gateway, "AssistantRepository", _Repository)
    _configure_valid_assistant_execution_gate(monkeypatch)

    result = gateway.validate_assistant_response_attachment(
        object(),
        conversation_id=str(conversation_id),
        assistant_response_id=str(response_id),
    )

    assert result["conversation_response_gateway_ready"] is True
    assert result["assistant_execution_evidence_gate"]["authority"] == "postgresql"
    assert result["blocking_issues"] == []


def test_attachment_rejects_cross_organization_response(monkeypatch) -> None:
    conversation_id = uuid4()
    response_id = uuid4()
    _Repository.conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=uuid4(),
        ownership_scope="organization",
    )
    _Repository.response = SimpleNamespace(
        assistant_response_id=response_id,
        citation_verification_id=uuid4(),
        organization_id=uuid4(),
        ownership_scope="organization",
    )
    _Repository.verification = SimpleNamespace(assistant_runtime_id=None)
    monkeypatch.setattr(gateway, "AssistantRepository", _Repository)

    result = gateway.validate_assistant_response_attachment(
        object(),
        conversation_id=str(conversation_id),
        assistant_response_id=str(response_id),
    )

    assert result["conversation_response_gateway_ready"] is False
    assert "assistant_response_organization_mismatch" in _issue_codes(result)


def test_attachment_rejects_global_response_evidence(monkeypatch) -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    response_id = uuid4()
    _Repository.conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )
    _Repository.response = SimpleNamespace(
        assistant_response_id=response_id,
        citation_verification_id=uuid4(),
        organization_id=None,
        ownership_scope="global",
    )
    _Repository.verification = SimpleNamespace(assistant_runtime_id=None)
    monkeypatch.setattr(gateway, "AssistantRepository", _Repository)

    result = gateway.validate_assistant_response_attachment(
        object(),
        conversation_id=str(conversation_id),
        assistant_response_id=str(response_id),
    )

    assert result["conversation_response_gateway_ready"] is False
    assert "assistant_response_not_organization_scoped" in _issue_codes(result)


def test_migration_declares_persistent_response_organization_invariant() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision: str = "20260816_999"' in source
    assert 'down_revision: str | Sequence[str] | None = "20260816_998"' in source
    assert "uq_ai_assistant_responses_id_organization" in source
    assert "fk_ai_conversation_turns_response_organization" in source
    assert '["assistant_response_id", "organization_id"]' in source
    assert "response.ownership_scope <> 'organization'" in source
    assert "response.organization_id IS DISTINCT FROM turn.organization_id" in source
