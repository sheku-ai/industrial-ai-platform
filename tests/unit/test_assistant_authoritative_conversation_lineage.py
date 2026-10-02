from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.assistant_runtime import AssistantDefinition, Conversation
from app.repositories.assistant import AssistantRepository

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "apps/api/alembic/versions/20260923_2830_assistant_session_conversation_turn_authoritative_lineage.py"
)


class _Session:
    def __init__(self, records: dict[tuple[Any, uuid.UUID], Any] | None = None) -> None:
        self.records = records or {}
        self.added: list[Any] = []

    def get(self, model: Any, identifier: uuid.UUID) -> Any | None:
        return self.records.get((model, identifier))

    def add(self, record: Any) -> None:
        self.added.append(record)

    def flush(self) -> None:
        return None


def _owned(organization_id: uuid.UUID, assistant_id: uuid.UUID, session_id: uuid.UUID) -> tuple[Any, Any]:
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        data_origin="operational",
    )
    response = SimpleNamespace(
        assistant_response_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        response_text="answer",
        response_format="markdown",
        citation_verification_passed=True,
        verified_citation_count=1,
        missing_citation_count=0,
        invalid_citation_count=0,
        ordered_citations=[],
    )
    return conversation, response


def test_assistant_session_rejects_caller_organization_mismatch() -> None:
    assistant_id, org_a, org_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id, organization_id=org_a, ownership_scope="organization", data_origin="operational"
    )
    db = _Session({(AssistantDefinition, assistant_id): assistant})

    with pytest.raises(ValueError, match="assistant organization is inconsistent"):
        AssistantRepository(db).create_assistant_session(assistant_id=assistant_id, execution_organization_id=org_b)

    assert db.added == []


def test_assistant_session_accepts_persisted_organization() -> None:
    assistant_id, org = uuid.uuid4(), uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id, organization_id=org, ownership_scope="organization", data_origin="operational"
    )
    db = _Session({(AssistantDefinition, assistant_id): assistant})

    record = AssistantRepository(db).create_assistant_session(assistant_id=assistant_id, execution_organization_id=org)

    assert record.organization_id == org
    assert record.ownership_scope == "organization"
    assert db.added == [record]


def test_global_assistant_is_not_promoted_to_organization_session() -> None:
    assistant_id, org = uuid.uuid4(), uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id, organization_id=None, ownership_scope="global", data_origin="reference"
    )
    db = _Session({(AssistantDefinition, assistant_id): assistant})

    with pytest.raises(ValueError, match="cannot be promoted"):
        AssistantRepository(db).create_assistant_session(assistant_id=assistant_id, execution_organization_id=org)

    assert db.added == []


@pytest.mark.parametrize("mismatch", ["organization", "assistant", "session", "null_organization"])
def test_direct_turn_create_rejects_contradictory_lineage(mismatch: str) -> None:
    org, assistant, session = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation, _ = _owned(org, assistant, session)
    args: dict[str, Any] = {
        "conversation_id": conversation.conversation_id,
        "turn_index": 0,
        "turn_role": "assistant",
        "organization_id": org,
        "data_origin": "operational",
    }
    if mismatch == "organization":
        args["organization_id"] = uuid.uuid4()
    elif mismatch == "assistant":
        args["assistant_id"] = uuid.uuid4()
    elif mismatch == "session":
        args["assistant_session_id"] = uuid.uuid4()
    else:
        args["organization_id"] = None
    db = _Session({(Conversation, conversation.conversation_id): conversation})

    with pytest.raises(ValueError):
        AssistantRepository(db).create_conversation_turn(**args)

    assert db.added == []


def test_direct_turn_create_uses_persisted_conversation_lineage() -> None:
    org, assistant, session = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation, _ = _owned(org, assistant, session)
    db = _Session({(Conversation, conversation.conversation_id): conversation})

    turn = AssistantRepository(db).create_conversation_turn(
        conversation_id=conversation.conversation_id,
        turn_index=0,
        turn_role="user",
        organization_id=org,
        data_origin="operational",
    )

    assert turn.organization_id == org
    assert turn.assistant_id == assistant
    assert turn.assistant_session_id == session


@pytest.mark.parametrize("mismatch", ["organization", "assistant", "session"])
def test_direct_turn_create_rejects_response_lineage_mismatch(mismatch: str) -> None:
    org, assistant, session = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation, response = _owned(org, assistant, session)
    if mismatch == "organization":
        response.organization_id = uuid.uuid4()
    elif mismatch == "assistant":
        response.assistant_id = uuid.uuid4()
    else:
        response.assistant_session_id = uuid.uuid4()
    db = _Session(
        {
            (Conversation, conversation.conversation_id): conversation,
            # Repository response lookup is patched below to isolate the boundary.
        }
    )
    repository = AssistantRepository(db)
    repository.get_assistant_response = lambda _identifier: response  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="assistant response lineage"):
        repository.create_conversation_turn(
            conversation_id=conversation.conversation_id,
            turn_index=0,
            turn_role="assistant",
            assistant_response_id=response.assistant_response_id,
            organization_id=org,
            data_origin="operational",
        )

    assert db.added == []


def test_migration_has_null_aware_child_and_parent_enforcement() -> None:
    source = MIGRATION.read_text()
    assert 'down_revision: str | Sequence[str] | None = "20260923_2820"' in source
    assert "IS NOT DISTINCT FROM NEW.organization_id" in source
    assert "conversation_turns" in source and "assistant_responses" in source
    assert "CREATE CONSTRAINT TRIGGER" in source
    assert "assistant_definitions" in source and "conversations" in source
    assert "PRECHECKS" in source
    assert "UPDATE " not in source.upper()


@pytest.mark.parametrize("mismatch", ["session", "assistant", "organization"])
def test_repository_response_attachment_rejects_mismatched_parent(mismatch: str) -> None:
    org, assistant, session = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation, response = _owned(org, assistant, session)
    if mismatch == "session":
        response.assistant_session_id = uuid.uuid4()
    elif mismatch == "assistant":
        response.assistant_id = uuid.uuid4()
    else:
        response.organization_id = uuid.uuid4()
    db = _Session()
    repository = AssistantRepository(db)
    repository.get_conversation = lambda _identifier: conversation  # type: ignore[method-assign]
    repository.get_assistant_response = lambda _identifier: response  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="assistant response lineage"):
        repository.attach_assistant_response_turn(
            conversation_id=conversation.conversation_id,
            assistant_response_id=response.assistant_response_id,
        )

    assert db.added == []


def test_repository_response_attachment_accepts_matching_persisted_lineage() -> None:
    org, assistant, session = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation, response = _owned(org, assistant, session)
    repository = AssistantRepository(_Session())
    repository.get_conversation = lambda _identifier: conversation  # type: ignore[method-assign]
    repository.get_assistant_response = lambda _identifier: response  # type: ignore[method-assign]
    repository.resolve_assistant_run_id_for_response = lambda _identifier: None  # type: ignore[method-assign]
    repository.find_conversation_turn_for_assistant_response = lambda _identifier: None  # type: ignore[method-assign]
    repository.get_next_conversation_turn_index = lambda _conversation_id: 0  # type: ignore[method-assign]

    marker = object()
    calls: list[dict[str, Any]] = []
    repository.create_conversation_turn = lambda **kwargs: calls.append(kwargs) or marker  # type: ignore[method-assign]

    result = repository.attach_assistant_response_turn(
        conversation_id=conversation.conversation_id,
        assistant_response_id=response.assistant_response_id,
    )

    assert result is marker
    assert calls[0]["organization_id"] == org
    assert calls[0]["assistant_id"] == assistant
    assert calls[0]["assistant_session_id"] == session
