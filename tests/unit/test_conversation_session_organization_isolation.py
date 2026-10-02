from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.repositories.assistant import AssistantRepository
from app.services import conversation_gateway

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps/api/alembic/versions/20260923_2800_assistant_session_conversation_ownership.py"
)


class _GatewayRepository:
    def __init__(
        self,
        *,
        assistant_id: uuid.UUID,
        session: Any | None,
        session_exists: bool,
    ) -> None:
        self.assistant_id = assistant_id
        self.session = session
        self.session_exists = session_exists

    def get_assistant_definition(self, assistant_id: uuid.UUID) -> Any | None:
        if assistant_id == self.assistant_id:
            return SimpleNamespace(assistant_id=assistant_id)
        return None

    def get_scoped_assistant_session(
        self,
        assistant_session_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
    ) -> Any | None:
        if (
            self.session is not None
            and self.session.assistant_session_id == assistant_session_id
            and self.session.organization_id == organization_id
            and self.session.ownership_scope == "organization"
        ):
            return self.session
        return None

    def assistant_session_exists(self, assistant_session_id: uuid.UUID) -> bool:
        return self.session_exists


def _validate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    session_id: uuid.UUID,
    session: Any | None,
    session_exists: bool,
) -> dict[str, Any]:
    repository = _GatewayRepository(
        assistant_id=assistant_id,
        session=session,
        session_exists=session_exists,
    )
    monkeypatch.setattr(conversation_gateway, "AssistantRepository", lambda db: repository)
    return conversation_gateway.validate_conversation_creation(
        object(),
        organization_id=organization_id,
        assistant_id=str(assistant_id),
        assistant_session_id=str(session_id),
    )


def _issue_codes(result: dict[str, Any]) -> list[str]:
    return [item["code"] for item in result["blocking_issues"]]


def test_conversation_accepts_session_from_same_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=session_id,
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )

    result = _validate(
        monkeypatch,
        organization_id=organization_id,
        assistant_id=assistant_id,
        session_id=session_id,
        session=session,
        session_exists=True,
    )

    assert result["conversation_gateway_ready"] is True
    assert result["blocking_issues"] == []


def test_conversation_rejects_session_from_another_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=session_id,
        assistant_id=assistant_id,
        organization_id=uuid.uuid4(),
        ownership_scope="organization",
    )

    result = _validate(
        monkeypatch,
        organization_id=organization_id,
        assistant_id=assistant_id,
        session_id=session_id,
        session=session,
        session_exists=True,
    )

    assert _issue_codes(result) == ["assistant_session_not_authorized_for_organization"]


def test_conversation_preserves_unknown_session_result(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _validate(
        monkeypatch,
        organization_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session=None,
        session_exists=False,
    )

    assert _issue_codes(result) == ["assistant_session_not_found"]


def test_conversation_does_not_infer_legacy_session_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=session_id,
        assistant_id=assistant_id,
        organization_id=None,
        ownership_scope="legacy_unscoped",
    )

    result = _validate(
        monkeypatch,
        organization_id=uuid.uuid4(),
        assistant_id=assistant_id,
        session_id=session_id,
        session=session,
        session_exists=True,
    )

    assert _issue_codes(result) == ["assistant_session_not_authorized_for_organization"]
    assert session.organization_id is None
    assert session.ownership_scope == "legacy_unscoped"


def test_conversation_rejects_session_for_different_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=session_id,
        assistant_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
    )

    result = _validate(
        monkeypatch,
        organization_id=organization_id,
        assistant_id=assistant_id,
        session_id=session_id,
        session=session,
        session_exists=True,
    )

    assert _issue_codes(result) == ["assistant_session_assistant_mismatch"]


class _PersistenceSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, record: Any) -> None:
        self.added.append(record)

    def flush(self) -> None:
        return None


def test_direct_conversation_creation_persists_same_organization_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=session_id,
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
    )
    persistence = _PersistenceSession()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "get_scoped_assistant_session", lambda *args, **kwargs: session)

    conversation = repository.create_conversation(
        organization_id=organization_id,
        data_origin="operational",
        assistant_id=assistant_id,
        assistant_session_id=session_id,
    )

    assert persistence.added == [conversation]
    assert conversation.organization_id == organization_id
    assert conversation.assistant_session_id == session_id


def test_direct_conversation_creation_rejects_unscoped_session_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = _PersistenceSession()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "get_scoped_assistant_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(repository, "assistant_session_exists", lambda *args, **kwargs: True)

    with pytest.raises(ValueError, match="assistant_session_not_authorized_for_organization"):
        repository.create_conversation(
            organization_id=uuid.uuid4(),
            data_origin="operational",
            assistant_id=uuid.uuid4(),
            assistant_session_id=uuid.uuid4(),
        )

    assert persistence.added == []


def test_direct_conversation_creation_preserves_unknown_session_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = _PersistenceSession()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "get_scoped_assistant_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(repository, "assistant_session_exists", lambda *args, **kwargs: False)

    with pytest.raises(ValueError, match="assistant_session_not_found"):
        repository.create_conversation(
            organization_id=uuid.uuid4(),
            data_origin="operational",
            assistant_id=uuid.uuid4(),
            assistant_session_id=uuid.uuid4(),
        )

    assert persistence.added == []


def test_conversation_session_attachment_rejects_cross_organization_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    conversation = SimpleNamespace(
        conversation_id=uuid.uuid4(),
        organization_id=organization_id,
        assistant_id=uuid.uuid4(),
        assistant_session_id=None,
    )
    persistence = _PersistenceSession()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "get_scoped_conversation", lambda *args, **kwargs: conversation)
    monkeypatch.setattr(repository, "get_scoped_assistant_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(repository, "assistant_session_exists", lambda *args, **kwargs: True)

    with pytest.raises(ValueError, match="assistant_session_not_authorized_for_organization"):
        repository.attach_conversation_session(
            conversation_id=conversation.conversation_id,
            assistant_session_id=uuid.uuid4(),
            organization_id=organization_id,
        )

    assert conversation.assistant_session_id is None
    assert persistence.added == []


def test_migration_declares_authoritative_session_organization_invariant() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision: str = "20260923_2800"' in source
    assert 'down_revision: str | Sequence[str] | None = "20260827_2700"' in source
    assert "uq_ai_assistant_sessions_id_organization" in source
    assert "fk_ai_conversations_session_organization" in source
    assert '["assistant_session_id", "organization_id"]' in source
    assert "session.ownership_scope <> 'organization'" in source
    assert "session.organization_id IS DISTINCT FROM conversation.organization_id" in source
    assert "UPDATE ai." not in source
