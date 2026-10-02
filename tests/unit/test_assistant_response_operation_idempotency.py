from __future__ import annotations

import os
import runpy
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Index, create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantLlmExecution,
    ConversationTurn,
)
from app.repositories.assistant import AssistantRepository
from app.services import assistant_citation_verification_runtime, assistant_response_runtime, chat_runtime
from app.services.conversation_runtime import find_chat_request_turn


def _response_evidence(organization_id: uuid.UUID | None) -> SimpleNamespace:
    scope = "organization" if organization_id else "global"
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    execution = SimpleNamespace(
        llm_execution_id=uuid.uuid4(),
        prompt_package_id=uuid.uuid4(),
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        organization_id=organization_id,
        ownership_scope=scope,
        raw_output_text="answer",
    )
    context = SimpleNamespace(
        context_package_id=uuid.uuid4(),
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        organization_id=organization_id,
        ownership_scope=scope,
        ordered_citations=[{"citation_id": "citation-1"}],
    )
    prompt = SimpleNamespace(
        prompt_package_id=execution.prompt_package_id,
        context_package_id=context.context_package_id,
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        organization_id=organization_id,
        ownership_scope=scope,
    )
    citation = SimpleNamespace(
        citation_verification_id=uuid.uuid4(),
        llm_execution_id=execution.llm_execution_id,
        prompt_package_id=prompt.prompt_package_id,
        context_package_id=context.context_package_id,
        organization_id=organization_id,
        ownership_scope=scope,
        verified_citation_count=1,
        missing_citation_count=0,
        invalid_citation_count=0,
    )
    return SimpleNamespace(citation=citation, execution=execution, prompt=prompt, context=context)


class _ResponseDb:
    def __init__(self, evidence: SimpleNamespace) -> None:
        self.evidence = evidence
        self.response: SimpleNamespace | None = None
        self.response_count = 0
        self.race = False

    def begin_nested(self) -> Any:
        return nullcontext()

    def commit(self) -> None:
        return None


class _ResponseRepository:
    def __init__(self, db: _ResponseDb) -> None:
        self.db = db

    def get_scoped_artifact(
        self,
        model: type,
        identifier: Any,
        artifact_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool,
    ) -> Any:
        record = (
            self.db.evidence.citation
            if model is AssistantCitationVerification
            else self.db.evidence.execution
            if model is AssistantLlmExecution
            else None
        )
        if record is None or record.organization_id != organization_id:
            return None
        if record.organization_id is None and not platform_scope:
            return None
        return record if getattr(record, identifier.key) == artifact_id else None

    def list_assistant_responses_by_citation_verification(self, **kwargs: Any) -> list[Any]:
        return [self.db.response] if self.db.response is not None else []

    def get_llm_execution(self, identifier: uuid.UUID) -> Any:
        return self.db.evidence.execution

    def get_prompt_package(self, identifier: uuid.UUID) -> Any:
        return self.db.evidence.prompt

    def get_context_package(self, identifier: uuid.UUID) -> Any:
        return self.db.evidence.context

    def create_assistant_response(self, **kwargs: Any) -> Any:
        self.db.response_count += 1
        response = SimpleNamespace(
            assistant_response_id=uuid.uuid4(),
            organization_id=self.db.evidence.citation.organization_id,
            ownership_scope=self.db.evidence.citation.ownership_scope,
            created_at=None,
            updated_at=None,
            **kwargs,
        )
        self.db.response = response
        if self.db.race:
            original = Exception("unique violation")
            original.diag = SimpleNamespace(  # type: ignore[attr-defined]
                constraint_name=assistant_response_runtime.ASSISTANT_RESPONSE_IDEMPOTENCY_CONSTRAINT
            )
            raise IntegrityError("insert", {}, original)
        return response

    def mark_llm_execution_final_response_created(self, identifier: uuid.UUID) -> None:
        return None

    def mark_prompt_package_answer_generated(self, identifier: uuid.UUID) -> None:
        return None


def _response_runtime(
    monkeypatch: pytest.MonkeyPatch,
    db: _ResponseDb,
    response_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    monkeypatch.setattr(assistant_response_runtime, "AssistantRepository", _ResponseRepository)
    monkeypatch.setattr(
        assistant_response_runtime,
        "build_assistant_response_gateway",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    return assistant_response_runtime.build_assistant_response_runtime(
        db,  # type: ignore[arg-type]
        citation_verification_id=str(db.evidence.citation.citation_verification_id),
        organization_id=db.evidence.citation.organization_id,
        response_metadata=response_metadata,
        persist_snapshot=False,
    )


def test_first_response_and_equivalent_retry_reuse_identity_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    first = _response_runtime(monkeypatch, db)
    retry = _response_runtime(monkeypatch, db)

    assert first is not None and retry is not None
    assert db.response_count == 1
    assert first["assistant_response_id"] == retry["assistant_response_id"]
    for key in (
        "llm_execution_id",
        "citation_verification_id",
        "prompt_package_id",
        "context_package_id",
        "assistant_id",
        "assistant_session_id",
    ):
        assert first[key] == retry[key]


def test_changed_authoritative_llm_output_conflicts_without_mutating_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    first = _response_runtime(monkeypatch, db)
    assert first is not None
    db.evidence.execution.raw_output_text = "different answer"

    conflict = _response_runtime(monkeypatch, db)

    assert conflict is not None
    assert conflict["blocking_issues"][0]["code"] == "assistant_response_idempotency_conflict"
    assert db.response_count == 1
    assert db.response is not None
    assert db.response.response_text == "answer"


def test_response_unique_race_resolves_persisted_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    db.race = True

    result = _response_runtime(monkeypatch, db)

    assert result is not None
    assert result["passed"] is True
    assert result["assistant_response_id"] == str(db.response.assistant_response_id)


@pytest.mark.parametrize("organization_id", [uuid.uuid4(), None])
def test_response_scope_matches_persisted_organization_or_global_scope(
    monkeypatch: pytest.MonkeyPatch,
    organization_id: uuid.UUID | None,
) -> None:
    db = _ResponseDb(_response_evidence(organization_id))
    assert _response_runtime(monkeypatch, db)["passed"] is True
    if organization_id is not None:
        denied = assistant_response_runtime.build_assistant_response_runtime(
            db,  # type: ignore[arg-type]
            citation_verification_id=str(db.evidence.citation.citation_verification_id),
            organization_id=uuid.uuid4(),
            persist_snapshot=False,
        )
        assert denied is None


def test_chat_input_fingerprint_ignores_observability_and_detects_changed_input() -> None:
    base = {
        "message": "same text",
        "requested_by": "user-1",
        "runtime_context": {"top_k": 5, "correlation_id": "trace-1"},
        "runtime_metadata": {"locale": "en", "idempotency_key": "operation-1"},
    }
    fingerprint = chat_runtime._chat_input_fingerprint(**base)
    assert fingerprint == chat_runtime._chat_input_fingerprint(
        **{
            **base,
            "runtime_context": {"top_k": 5, "correlation_id": "trace-2"},
            "runtime_metadata": {"locale": "en", "idempotency_key": "operation-2"},
        }
    )
    assert fingerprint != chat_runtime._chat_input_fingerprint(**{**base, "message": "changed"})
    assert fingerprint != chat_runtime._chat_input_fingerprint(**{**base, "runtime_context": {"top_k": 10}})
    assert fingerprint != chat_runtime._chat_input_fingerprint(**{**base, "runtime_metadata": {"locale": "es"}})


def test_chat_retry_requires_persisted_input_identity() -> None:
    fingerprint = chat_runtime._chat_input_fingerprint(
        message="hello", requested_by=None, runtime_context={}, runtime_metadata={}
    )
    turn = SimpleNamespace(input_text="hello", turn_metadata={"chat_input_fingerprint": fingerprint})
    assert chat_runtime._chat_turn_matches_input(turn, message="hello", fingerprint=fingerprint)
    assert not chat_runtime._chat_turn_matches_input(turn, message="different", fingerprint=fingerprint)
    assert not chat_runtime._chat_turn_matches_input(
        SimpleNamespace(input_text="hello", turn_metadata={}),
        message="hello",
        fingerprint=fingerprint,
    )


def test_chat_key_lookup_is_scoped_to_organization_and_assistant() -> None:
    class CapturingDb:
        statement: Any = None

        def scalar(self, statement: Any) -> None:
            self.statement = statement
            return None

    db = CapturingDb()
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    find_chat_request_turn(  # type: ignore[arg-type]
        db, organization_id=organization_id, assistant_id=assistant_id, request_id="operation-1"
    )
    sql = str(db.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert str(organization_id) in sql
    assert str(assistant_id) in sql
    assert "conversation_turns.request_id = 'operation-1'" in sql


def test_one_assistant_turn_per_response_has_postgresql_unique_index() -> None:
    index = next(
        index
        for index in ConversationTurn.__table__.indexes
        if isinstance(index, Index) and index.name == "uq_ai_conversation_turns_response_identity"
    )
    assert index.unique is True
    assert [column.name for column in index.columns] == ["assistant_response_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "assistant_response_id IS NOT NULL"


class _MigrationResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> _MigrationResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self.row


def test_migration_prechecks_duplicates_before_unique_index(monkeypatch: pytest.MonkeyPatch) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "apps/api/alembic/versions/20260924_2840_assistant_response_idempotency.py"
    )
    migration = SimpleNamespace(**runpy.run_path(str(path)))
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class Connection:
        def execute(self, statement: Any, params: Any = None) -> _MigrationResult:
            assert "HAVING count(*) > 1" in str(statement) or "FROM pg_indexes" in str(statement)
            return _MigrationResult(None)

    monkeypatch.setattr(migration.op, "get_bind", lambda: Connection())
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: created.append((args, kwargs)))
    migration.upgrade()
    assert migration.revision == "20260924_2840"
    assert migration.down_revision == "20260923_2830"
    assert created[0][0] == (
        "uq_ai_conversation_turns_response_identity",
        "conversation_turns",
        ["assistant_response_id"],
    )
    assert created[0][1]["unique"] is True
    assert created[1][0] == (
        "uq_ai_assistant_citation_verifications_llm_execution",
        "assistant_citation_verifications",
        ["llm_execution_id"],
    )
    assert created[1][1]["unique"] is True

    class DuplicateConnection:
        def execute(self, statement: Any, params: Any = None) -> _MigrationResult:
            return _MigrationResult({"assistant_response_id": uuid.uuid4(), "row_count": 2})

    monkeypatch.setattr(migration.op, "get_bind", lambda: DuplicateConnection())
    with pytest.raises(RuntimeError, match="historical turns"):
        migration.upgrade()
    assert len(created) == 2


class _AttachmentRepository(AssistantRepository):
    def __init__(self) -> None:
        self.organization_id = uuid.uuid4()
        self.assistant_id = uuid.uuid4()
        self.session_id = uuid.uuid4()
        self.response_id = uuid.uuid4()
        self.first_conversation_id = uuid.uuid4()
        self.second_conversation_id = uuid.uuid4()
        self.turn: SimpleNamespace | None = None
        self.created_count = 0

    def get_conversation(self, conversation_id: uuid.UUID) -> Any:
        return SimpleNamespace(
            conversation_id=conversation_id,
            organization_id=self.organization_id,
            ownership_scope="organization",
            data_origin="operational",
            assistant_id=self.assistant_id,
            assistant_session_id=self.session_id,
        )

    def get_assistant_response(self, response_id: uuid.UUID) -> Any:
        assert response_id == self.response_id
        return SimpleNamespace(
            assistant_response_id=self.response_id,
            organization_id=self.organization_id,
            ownership_scope="organization",
            assistant_id=self.assistant_id,
            assistant_session_id=self.session_id,
            response_text="answer",
            response_format="markdown",
            citation_verification_passed=True,
            verified_citation_count=1,
            missing_citation_count=0,
            invalid_citation_count=0,
            ordered_citations=[],
        )

    def resolve_assistant_run_id_for_response(self, response_id: uuid.UUID) -> None:
        return None

    def find_conversation_turn_for_assistant_response(self, response_id: uuid.UUID) -> Any:
        return self.turn

    def get_next_conversation_turn_index(self, conversation_id: uuid.UUID) -> int:
        return 1

    def create_conversation_turn(self, **kwargs: Any) -> Any:
        self.created_count += 1
        self.turn = SimpleNamespace(
            conversation_turn_id=uuid.uuid4(),
            organization_id=kwargs["organization_id"],
            ownership_scope="organization",
            conversation_id=kwargs["conversation_id"],
            assistant_id=kwargs["assistant_id"],
            assistant_session_id=kwargs["assistant_session_id"],
            assistant_response_id=kwargs["assistant_response_id"],
            assistant_run_id=kwargs["assistant_run_id"],
            output_text=kwargs["output_text"],
        )
        return self.turn


def test_attachment_retry_reuses_one_turn_and_cross_conversation_conflicts() -> None:
    repository = _AttachmentRepository()
    first = repository.attach_assistant_response_turn(
        conversation_id=repository.first_conversation_id,
        assistant_response_id=repository.response_id,
    )
    retry = repository.attach_assistant_response_turn(
        conversation_id=repository.first_conversation_id,
        assistant_response_id=repository.response_id,
    )
    assert first is retry
    assert repository.created_count == 1
    assert first.organization_id == repository.organization_id
    assert first.assistant_id == repository.assistant_id
    assert first.assistant_session_id == repository.session_id
    with pytest.raises(ValueError, match="another conversation"):
        repository.attach_assistant_response_turn(
            conversation_id=repository.second_conversation_id,
            assistant_response_id=repository.response_id,
        )
    assert repository.created_count == 1


@pytest.mark.parametrize("changed_input", ["message", "context", "conversation"])
def test_chat_retry_conflicts_before_downstream_execution(
    monkeypatch: pytest.MonkeyPatch,
    changed_input: str,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message = "original message"
    fingerprint = chat_runtime._chat_input_fingerprint(
        message=message,
        requested_by=None,
        runtime_context={"top_k": 5},
        runtime_metadata={"idempotency_key": "operation-1"},
    )
    turn = SimpleNamespace(
        conversation_turn_id=uuid.uuid4(),
        conversation_id=conversation_id,
        input_text=message,
        turn_metadata={"chat_input_fingerprint": fingerprint},
    )
    monkeypatch.setattr(
        chat_runtime,
        "validate_chat_request",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    monkeypatch.setattr(chat_runtime, "AssistantRepository", lambda db: object())
    monkeypatch.setattr(chat_runtime, "find_chat_request_turn", lambda *args, **kwargs: turn)

    result = chat_runtime.build_chat_runtime(
        object(),  # type: ignore[arg-type]
        assistant_id=str(assistant_id),
        organization_id=organization_id,
        conversation_id=str(uuid.uuid4()) if changed_input == "conversation" else None,
        message="changed message" if changed_input == "message" else message,
        runtime_context={"top_k": 10 if changed_input == "context" else 5},
        runtime_metadata={"idempotency_key": "operation-1"},
    )

    assert result["passed"] is False
    expected_code = (
        "idempotency_key_conversation_mismatch" if changed_input == "conversation" else "idempotency_key_input_mismatch"
    )
    assert result["blocking_issues"][0]["code"] == expected_code


def test_postgresql_rejects_duplicate_response_identity_directly() -> None:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            deployed = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'ai' AND tablename = 'conversation_turns' "
                    "AND indexname = 'uq_ai_conversation_turns_response_identity'"
                )
            ).scalar_one()
            assert "UNIQUE INDEX" in deployed
            assert "assistant_response_id" in deployed
            citation_index = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'ai' AND tablename = 'assistant_citation_verifications' "
                    "AND indexname = 'uq_ai_assistant_citation_verifications_llm_execution'"
                )
            ).scalar_one()
            assert "UNIQUE INDEX" in citation_index
            assert "llm_execution_id" in citation_index
            connection.execute(text("CREATE TEMP TABLE response_identity_probe (assistant_response_id uuid)"))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX response_identity_probe_unique "
                    "ON response_identity_probe (assistant_response_id) "
                    "WHERE assistant_response_id IS NOT NULL"
                )
            )
            response_id = uuid.uuid4()
            connection.execute(
                text("INSERT INTO response_identity_probe (assistant_response_id) VALUES (:response_id)"),
                {"response_id": response_id},
            )
            connection.execute(
                text("INSERT INTO response_identity_probe (assistant_response_id) VALUES (NULL), (NULL)")
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("INSERT INTO response_identity_probe (assistant_response_id) VALUES (:response_id)"),
                    {"response_id": response_id},
                )
            connection.execute(text("CREATE TEMP TABLE citation_identity_probe (llm_execution_id uuid)"))
            connection.execute(
                text("CREATE UNIQUE INDEX citation_identity_probe_unique ON citation_identity_probe (llm_execution_id)")
            )
            connection.execute(
                text("INSERT INTO citation_identity_probe (llm_execution_id) VALUES (:execution_id)"),
                {"execution_id": response_id},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("INSERT INTO citation_identity_probe (llm_execution_id) VALUES (:execution_id)"),
                    {"execution_id": response_id},
                )
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize("recovery_stage", ["response", "citation", "llm"])
def test_chat_retry_recovers_persisted_response_citation_or_llm_without_new_run(
    monkeypatch: pytest.MonkeyPatch,
    recovery_stage: str,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    response_id = uuid.uuid4()
    citation_id = uuid.uuid4()
    user_turn = SimpleNamespace(
        conversation_turn_id=uuid.uuid4(),
        conversation_id=conversation_id,
        turn_index=0,
        turn_role="user",
        input_text="hello",
        turn_metadata={
            "chat_input_fingerprint": chat_runtime._chat_input_fingerprint(
                message="hello",
                requested_by=None,
                runtime_context={},
                runtime_metadata={"idempotency_key": "operation-1"},
            )
        },
    )
    response = SimpleNamespace(
        assistant_response_id=response_id,
        llm_execution_id=uuid.uuid4(),
        citation_verification_id=citation_id,
    )
    assistant_turn = SimpleNamespace(
        conversation_turn_id=uuid.uuid4(),
        conversation_id=conversation_id,
        turn_role="assistant",
        output_text="answer",
        ordered_citations=[],
        assistant_response_id=response_id,
        turn_metadata={"idempotency_key": "operation-1"},
    )
    conversation = SimpleNamespace(
        conversation_id=conversation_id,
        organization_id=organization_id,
        assistant_session_id=session_id,
        conversation_title="hello",
        runtime_context={},
    )
    actions: list[str] = []
    citation_recovered = False

    class Db:
        def commit(self) -> None:
            return None

    class Repository:
        def __init__(self, db: Any) -> None:
            return None

        def list_conversation_turns(self, identifier: uuid.UUID, *, limit: int) -> list[Any]:
            return [user_turn]

        def get_scoped_conversation(self, identifier: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
            return conversation

        def list_scoped_assistant_responses_for_run(self, **kwargs: Any) -> list[Any]:
            assert kwargs["assistant_run_id"] == run_id
            return [response] if recovery_stage == "response" else []

        def list_scoped_citation_verifications_for_run(self, **kwargs: Any) -> list[Any]:
            return (
                [SimpleNamespace(citation_verification_id=citation_id)]
                if recovery_stage != "llm" or citation_recovered
                else []
            )

        def list_scoped_llm_executions_for_run(self, **kwargs: Any) -> list[Any]:
            assert kwargs["assistant_run_id"] == run_id
            assert kwargs["conversation_id"] == conversation_id
            return [SimpleNamespace(llm_execution_id=response.llm_execution_id, execution_status="completed")]

        def get_assistant_response(self, identifier: uuid.UUID) -> Any:
            assert identifier == response_id
            return response

        def get_conversation_turn(self, identifier: uuid.UUID) -> Any:
            assert identifier == assistant_turn.conversation_turn_id
            return assistant_turn

    monkeypatch.setattr(chat_runtime, "AssistantRepository", Repository)
    monkeypatch.setattr(
        chat_runtime,
        "validate_chat_request",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    monkeypatch.setattr(chat_runtime, "find_chat_request_turn", lambda *args, **kwargs: user_turn)
    monkeypatch.setattr(
        chat_runtime,
        "resolve_conversation_context_package",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        chat_runtime,
        "resolve_interaction_decision",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(chat_runtime, "conversation_context_package_to_dict", lambda item: {})
    monkeypatch.setattr(chat_runtime, "interaction_decision_to_dict", lambda item: {})
    monkeypatch.setattr(chat_runtime, "conversation_turn_to_dict", lambda item: {})
    monkeypatch.setattr(
        chat_runtime,
        "resolve_interaction_execution_directive",
        lambda *args, **kwargs: SimpleNamespace(
            interaction_plan_id=uuid.uuid4(),
            planned_action="enterprise_search",
            enterprise_search_required=True,
        ),
    )
    monkeypatch.setattr(chat_runtime, "interaction_execution_directive_to_dict", lambda item: {})
    monkeypatch.setattr(
        chat_runtime,
        "_claim_idempotent_chat_execution",
        lambda *args, **kwargs: (
            str(session_id),
            {"assistant_run_id": str(run_id)},
            False,
        ),
    )
    monkeypatch.setattr(chat_runtime, "_conversation_payload", lambda *args, **kwargs: {})

    def recover_citation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal citation_recovered
        citation_recovered = True
        actions.append("rebuild_citation")
        assert kwargs["request_metadata"]["assistant_run_id"] == str(run_id)
        return {"citation_verification_id": str(citation_id), "blocking_issues": []}

    monkeypatch.setattr(chat_runtime, "build_assistant_citation_verification_runtime", recover_citation)
    monkeypatch.setattr(
        chat_runtime,
        "build_assistant_response_runtime",
        lambda *args, **kwargs: (
            actions.append("rebuild_response") or {"assistant_response_id": str(response_id), "blocking_issues": []}
        ),
    )
    monkeypatch.setattr(
        chat_runtime,
        "attach_assistant_response_to_conversation_runtime",
        lambda *args, **kwargs: (
            actions.append("attach_turn")
            or {"conversation_turn_id": str(assistant_turn.conversation_turn_id), "blocking_issues": []}
        ),
    )

    result = chat_runtime.build_chat_runtime(
        Db(),  # type: ignore[arg-type]
        assistant_id=str(assistant_id),
        organization_id=organization_id,
        message="hello",
        runtime_metadata={"idempotency_key": "operation-1"},
        persist_snapshot=False,
    )

    assert result["chat_completed"] is True
    assert result["assistant_response_id"] == str(response_id)
    assert result["llm_execution_id"] == str(response.llm_execution_id)
    assert result["citation_verification_id"] == str(citation_id)
    assert result["assistant_session_id"] == str(session_id)
    assert result["conversation_turns_created"] == 0
    assert (
        actions
        == {
            "response": ["attach_turn"],
            "citation": ["rebuild_response", "attach_turn"],
            "llm": ["rebuild_citation", "rebuild_response", "attach_turn"],
        }[recovery_stage]
    )


@pytest.mark.parametrize("changed_lineage", ["session", "citations"])
def test_response_retry_rejects_changed_session_or_citation_evidence(
    monkeypatch: pytest.MonkeyPatch,
    changed_lineage: str,
) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    first = _response_runtime(monkeypatch, db)
    assert first is not None
    if changed_lineage == "session":
        db.evidence.execution.assistant_session_id = uuid.uuid4()
    else:
        db.evidence.context.ordered_citations = [{"citation_id": "different"}]

    conflict = _response_runtime(monkeypatch, db)

    assert conflict is not None
    assert conflict["blocking_issues"][0]["code"] == "assistant_response_idempotency_conflict"
    assert db.response_count == 1
    assert db.response.assistant_response_id == uuid.UUID(first["assistant_response_id"])


def test_distinct_citation_identity_does_not_collapse_identical_answer_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    first_db = _ResponseDb(_response_evidence(organization_id))
    second_db = _ResponseDb(_response_evidence(organization_id))

    first = _response_runtime(monkeypatch, first_db)
    second = _response_runtime(monkeypatch, second_db)

    assert first is not None and second is not None
    assert first["response_text"] == second["response_text"]
    assert first["assistant_response_id"] != second["assistant_response_id"]
    assert first_db.response_count == second_db.response_count == 1


def test_response_metadata_input_conflicts_but_observability_change_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    first = _response_runtime(
        monkeypatch,
        db,
        {"locale": "en", "correlation_id": "first-attempt"},
    )
    replay = _response_runtime(
        monkeypatch,
        db,
        {"locale": "en", "correlation_id": "second-attempt"},
    )
    conflict = _response_runtime(monkeypatch, db, {"locale": "es"})

    assert first is not None and replay is not None and conflict is not None
    assert first["assistant_response_id"] == replay["assistant_response_id"]
    assert conflict["blocking_issues"][0]["code"] == "assistant_response_idempotency_conflict"
    assert db.response_count == 1
    assert db.response.response_metadata["locale"] == "en"


def test_historical_response_without_fingerprint_remains_readable_and_reusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ResponseDb(_response_evidence(uuid.uuid4()))
    first = _response_runtime(monkeypatch, db)
    assert first is not None
    db.response.response_metadata.pop("idempotency_input_fingerprint")

    retry = _response_runtime(monkeypatch, db)

    assert retry is not None
    assert retry["assistant_response_id"] == first["assistant_response_id"]
    assert db.response_count == 1


def test_citation_recovery_reuses_persisted_verification_and_rejects_changed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution = SimpleNamespace(
        llm_execution_id=uuid.uuid4(),
        prompt_package_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        assistant_session_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        raw_output_text="answer [citation:one]",
    )
    context = SimpleNamespace(context_package_id=uuid.uuid4(), ordered_citations=[{"citation_id": "citation:one"}])
    prompt = SimpleNamespace(
        prompt_package_id=execution.prompt_package_id,
        context_package_id=context.context_package_id,
        citation_section="citation:one",
    )

    class Db:
        def __init__(self) -> None:
            self.verification: Any = None
            self.created = 0
            self.race = False

        def begin_nested(self) -> Any:
            return nullcontext()

        def commit(self) -> None:
            return None

    class Repository:
        def __init__(self, session: Db) -> None:
            self.session = session

        def get_scoped_artifact(self, *args: Any, **kwargs: Any) -> Any:
            return execution

        def get_prompt_package(self, identifier: uuid.UUID) -> Any:
            return prompt

        def get_context_package(self, identifier: uuid.UUID) -> Any:
            return context

        def list_citation_verifications_by_llm_execution(self, identifier: uuid.UUID) -> list[Any]:
            return [self.session.verification] if self.session.verification else []

        def create_citation_verification(self, **kwargs: Any) -> Any:
            self.session.created += 1
            self.session.verification = SimpleNamespace(
                citation_verification_id=uuid.uuid4(),
                organization_id=organization_id,
                ownership_scope="organization",
                created_at=None,
                updated_at=None,
                **kwargs,
            )
            if self.session.race:
                self.session.race = False

                class UniqueViolation(Exception):
                    diag = SimpleNamespace(constraint_name="uq_ai_assistant_citation_verifications_llm_execution")

                raise IntegrityError("INSERT", {}, UniqueViolation())
            return self.session.verification

        def mark_llm_execution_citation_verified(self, identifier: uuid.UUID) -> None:
            return None

    monkeypatch.setattr(assistant_citation_verification_runtime, "AssistantRepository", Repository)
    monkeypatch.setattr(
        assistant_citation_verification_runtime,
        "build_assistant_citation_verification_gateway",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    monkeypatch.setattr(
        assistant_citation_verification_runtime,
        "_assistant_runtime_evidence",
        lambda *args, **kwargs: (SimpleNamespace(assistant_run_id=run_id), None),
    )
    db = Db()
    kwargs = {
        "llm_execution_id": str(execution.llm_execution_id),
        "organization_id": organization_id,
        "request_metadata": {"assistant_run_id": str(run_id)},
        "persist_snapshot": False,
    }
    first = assistant_citation_verification_runtime.build_assistant_citation_verification_runtime(db, **kwargs)
    replay = assistant_citation_verification_runtime.build_assistant_citation_verification_runtime(db, **kwargs)
    assert first is not None and replay is not None
    assert first["citation_verification_id"] == replay["citation_verification_id"]
    assert first["citation_runtime_created"] is True
    assert replay["citation_runtime_created"] is False
    assert db.created == 1

    race_db = Db()
    race_db.race = True
    race_winner = assistant_citation_verification_runtime.build_assistant_citation_verification_runtime(
        race_db, **kwargs
    )
    assert race_winner is not None
    assert race_winner["passed"] is True
    assert race_winner["citation_runtime_created"] is False
    assert race_db.created == 1

    execution.raw_output_text = "changed [citation:other]"
    conflict = assistant_citation_verification_runtime.build_assistant_citation_verification_runtime(db, **kwargs)
    assert conflict is not None
    assert conflict["blocking_issues"][0]["code"] == "citation_verification_idempotency_conflict"
    assert db.created == 1
