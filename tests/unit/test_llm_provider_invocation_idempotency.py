from __future__ import annotations

import os
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services import assistant_llm_execution_runtime as runtime


class Provider:
    def __init__(self, db: FakeDb) -> None:
        self.db = db
        self.calls = 0
        self.fail = False

    def execute(self, **kwargs: Any) -> runtime.AssistantLlmProviderExecutionResult:
        assert self.db.commits >= 2  # claim and running state precede dispatch
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider failure")
        return runtime.AssistantLlmProviderExecutionResult("answer", {"source": "test"})


class FakeDb:
    def __init__(self) -> None:
        self.organization_id = uuid.uuid4()
        self.plan = SimpleNamespace(
            gateway_id=uuid.uuid4(),
            prompt_package_id=uuid.uuid4(),
            assistant_id=uuid.uuid4(),
            assistant_session_id=uuid.uuid4(),
            organization_id=self.organization_id,
            ownership_scope="organization",
            provider_type="reference",
            provider_name="metadata-only",
            model_name="metadata-only",
            planned_temperature=0.0,
            planned_max_tokens=1024,
            planned_top_p=1.0,
            planned_stop_sequences=[],
            planned_seed=None,
            planned_timeout=30,
        )
        self.prompt = SimpleNamespace(
            prompt_package_id=self.plan.prompt_package_id,
            assistant_id=self.plan.assistant_id,
            assistant_session_id=self.plan.assistant_session_id,
            organization_id=self.organization_id,
            ownership_scope="organization",
            system_prompt="system",
            assistant_instructions="instructions",
            assembled_context="context",
            citation_section="citation",
        )
        self.execution: Any = None
        self.commits = 0
        self.race_constraint: str | None = None

    def begin_nested(self) -> Any:
        return nullcontext()

    def add(self, record: Any) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class Repository:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def get_scoped_artifact(
        self,
        model: Any,
        column: Any,
        identifier: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool,
    ) -> Any:
        if identifier == self.db.plan.gateway_id and organization_id == self.db.organization_id:
            return self.db.plan
        return None

    def get_prompt_package(self, identifier: uuid.UUID) -> Any:
        return self.db.prompt if identifier == self.db.prompt.prompt_package_id else None

    def list_llm_executions_for_plan(self, identifier: uuid.UUID) -> list[Any]:
        return [self.db.execution] if self.db.execution is not None and identifier == self.db.plan.gateway_id else []

    def create_llm_execution(self, **kwargs: Any) -> Any:
        if self.db.race_constraint:
            constraint = self.db.race_constraint
            self.db.race_constraint = None

            class UniqueViolation(Exception):
                diag = SimpleNamespace(constraint_name=constraint)

            raise IntegrityError("INSERT", {}, UniqueViolation())
        assert self.db.execution is None
        record = SimpleNamespace(
            llm_execution_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            provider_call_started_at=None,
            provider_call_finished_at=None,
            latency_ms=None,
            cost_metadata={},
            prompt_tokens_estimated=0,
            completion_tokens_estimated=0,
            total_tokens_estimated=0,
            citation_verification_completed=False,
            final_response_created=False,
            tool_called=False,
            workflow_executed=False,
            external_action_called=False,
            autonomous_execution=False,
            **{
                key: value
                for key, value in kwargs.items()
                if key
                not in {
                    "prompt_tokens_estimated",
                    "completion_tokens_estimated",
                    "total_tokens_estimated",
                    "latency_ms",
                    "cost_metadata",
                    "citation_verification_completed",
                    "final_response_created",
                    "tool_called",
                    "workflow_executed",
                    "external_action_called",
                    "autonomous_execution",
                }
            },
            ownership_scope="organization",
            organization_id=self.db.organization_id,
        )
        self.db.execution = record
        return record


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeDb, Provider]:
    db = FakeDb()
    provider = Provider(db)
    monkeypatch.setattr(runtime, "AssistantRepository", Repository)
    monkeypatch.setattr(runtime, "_local_mock_adapter", lambda: provider)
    monkeypatch.setattr(
        runtime,
        "build_assistant_llm_execution_gateway",
        lambda *args, **kwargs: {"blocking_issues": [], "warnings": []},
    )
    return db, provider


def invoke(
    db: FakeDb,
    metadata: dict[str, Any] | None = None,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    return runtime.build_assistant_llm_execution_runtime(
        db,  # type: ignore[arg-type]
        gateway_id=str(db.plan.gateway_id),
        organization_id=organization_id or db.organization_id,
        request_payload_metadata=metadata,
        persist_snapshot=False,
    )


def test_first_claim_precedes_provider_and_equivalent_retry_reuses_execution(
    harness: tuple[FakeDb, Provider],
) -> None:
    db, provider = harness
    first = invoke(db, {"locale": "en", "correlation_id": "first"})
    retry = invoke(db, {"locale": "en", "correlation_id": "second"})
    assert first is not None and retry is not None
    assert first["passed"] and retry["passed"]
    assert first["llm_execution_id"] == retry["llm_execution_id"]
    assert retry["idempotent_replay"] is True
    assert provider.calls == 1
    assert db.execution.execution_status == "completed"
    assert db.execution.provider_call_started_at is not None
    assert db.execution.provider_call_finished_at is not None


@pytest.mark.parametrize("changed", ["locale", "prompt", "assistant", "session", "organization"])
def test_same_plan_changed_authoritative_input_conflicts(
    harness: tuple[FakeDb, Provider],
    changed: str,
) -> None:
    db, provider = harness
    first = invoke(db, {"locale": "en"})
    assert first is not None and first["passed"]
    if changed == "locale":
        metadata = {"locale": "es"}
    else:
        metadata = {"locale": "en"}
        if changed == "prompt":
            db.prompt.assembled_context = "different"
        elif changed == "assistant":
            db.plan.assistant_id = db.prompt.assistant_id = uuid.uuid4()
        elif changed == "session":
            db.plan.assistant_session_id = db.prompt.assistant_session_id = uuid.uuid4()
        else:
            db.plan.organization_id = db.prompt.organization_id = uuid.uuid4()
    conflict = invoke(db, metadata)
    assert conflict is not None
    assert conflict["blocking_issues"][0]["code"] == "llm_provider_input_conflict"
    assert provider.calls == 1


def test_cross_organization_direct_invocation_is_rejected(harness: tuple[FakeDb, Provider]) -> None:
    db, provider = harness
    result = invoke(db, organization_id=uuid.uuid4())
    assert result is None
    assert provider.calls == 0


def test_identical_prompt_in_distinct_plan_is_new_operation(harness: tuple[FakeDb, Provider]) -> None:
    db, provider = harness
    first = invoke(db)
    assert first is not None and first["passed"]
    db.plan.gateway_id = uuid.uuid4()
    db.execution = None
    second = invoke(db)
    assert second is not None and second["passed"]
    assert first["llm_execution_id"] != second["llm_execution_id"]
    assert provider.calls == 2


@pytest.mark.parametrize("status", ["prepared", "running"])
def test_existing_unfinished_claim_prevents_second_call(
    harness: tuple[FakeDb, Provider],
    status: str,
) -> None:
    db, provider = harness
    first = invoke(db)
    assert first is not None
    db.execution.execution_status = status
    db.execution.raw_output_text = None
    result = invoke(db)
    assert result is not None
    assert result["blocking_issues"][0]["code"] == "llm_provider_claim_in_progress"
    assert provider.calls == 1


def test_failed_attempt_is_persisted_without_automatic_retry(harness: tuple[FakeDb, Provider]) -> None:
    db, provider = harness
    provider.fail = True
    failed = invoke(db)
    assert failed is not None
    assert failed["blocking_issues"][0]["code"] == "llm_provider_attempt_failed"
    assert db.execution.execution_status == "failed"
    provider.fail = False
    retry = invoke(db)
    assert retry is not None
    assert retry["blocking_issues"][0]["code"] == "llm_provider_attempt_failed"
    assert provider.calls == 1


def test_race_loser_reuses_equivalent_winner(harness: tuple[FakeDb, Provider]) -> None:
    db, provider = harness
    winner = invoke(db)
    assert winner is not None
    db.race_constraint = "uq_ai_assistant_llm_executions_gateway_claim"
    # Force the initial lookup to miss while the INSERT sees the winner.
    original = Repository.list_llm_executions_for_plan
    calls = 0

    def race_lookup(self: Repository, identifier: uuid.UUID) -> list[Any]:
        nonlocal calls
        calls += 1
        return [] if calls == 1 else original(self, identifier)

    Repository.list_llm_executions_for_plan = race_lookup
    try:
        replay = invoke(db)
    finally:
        Repository.list_llm_executions_for_plan = original
    assert replay is not None and replay["passed"]
    assert replay["llm_execution_id"] == winner["llm_execution_id"]
    assert provider.calls == 1


def test_unrelated_integrity_error_propagates(harness: tuple[FakeDb, Provider]) -> None:
    db, _ = harness
    db.race_constraint = "some_other_constraint"
    with pytest.raises(IntegrityError):
        invoke(db)


def test_legacy_completed_execution_without_fingerprint_remains_reusable(
    harness: tuple[FakeDb, Provider],
) -> None:
    db, provider = harness
    first = invoke(db)
    assert first is not None
    db.execution.request_payload_metadata.pop("idempotency_input_fingerprint")
    replay = invoke(db)
    assert replay is not None
    assert replay["blocking_issues"][0]["code"] == "llm_provider_legacy_claim_unverifiable"
    assert runtime.assistant_llm_execution_to_dict(db.execution)["llm_execution_id"] == first["llm_execution_id"]
    assert provider.calls == 1


def test_postgresql_provider_claim_index_and_lifecycle_without_persistent_rows() -> None:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname='ai' "
                    "AND tablename='assistant_llm_executions' "
                    "AND indexname='uq_ai_assistant_llm_executions_gateway_claim'"
                )
            ).scalar_one()
            assert "UNIQUE INDEX" in definition and "(gateway_id)" in definition
            for column in ("provider_call_started_at", "provider_call_finished_at"):
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_schema='ai' AND table_name='assistant_llm_executions' "
                            "AND column_name=:column"
                        ),
                        {"column": column},
                    ).scalar_one()
                    == 1
                )
            connection.execute(
                text(
                    "CREATE TEMP TABLE provider_claim_probe "
                    "(LIKE ai.assistant_llm_executions INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
                )
            )
            gateway_id = uuid.uuid4()
            prompt_id = uuid.uuid4()
            assistant_id = uuid.uuid4()
            for execution_id, plan_id, status in (
                (uuid.uuid4(), gateway_id, "failed"),
                (uuid.uuid4(), uuid.uuid4(), "running"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO provider_claim_probe "
                        "(llm_execution_id,gateway_id,prompt_package_id,assistant_id,execution_status) "
                        "VALUES (:execution_id,:plan_id,:prompt_id,:assistant_id,:status)"
                    ),
                    {
                        "execution_id": execution_id,
                        "plan_id": plan_id,
                        "prompt_id": prompt_id,
                        "assistant_id": assistant_id,
                        "status": status,
                    },
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO provider_claim_probe "
                        "(llm_execution_id,gateway_id,prompt_package_id,assistant_id,execution_status) "
                        "VALUES (:execution_id,:plan_id,:prompt_id,:assistant_id,'prepared')"
                    ),
                    {
                        "execution_id": uuid.uuid4(),
                        "plan_id": gateway_id,
                        "prompt_id": prompt_id,
                        "assistant_id": assistant_id,
                    },
                )
            assert connection.execute(text("SELECT count(*) FROM provider_claim_probe")).scalar_one() == 2
            transaction.rollback()
            assert connection.execute(text("SELECT to_regclass('pg_temp.provider_claim_probe')")).scalar_one() is None
    finally:
        engine.dispose()


def test_concurrent_reentry_observes_running_claim_before_provider_finishes(
    harness: tuple[FakeDb, Provider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, provider = harness
    original_execute = provider.execute
    overlapping: list[dict[str, Any] | None] = []

    def execute_with_overlap(**kwargs: Any) -> runtime.AssistantLlmProviderExecutionResult:
        overlapping.append(invoke(db))
        return original_execute(**kwargs)

    monkeypatch.setattr(provider, "execute", execute_with_overlap)
    result = invoke(db)
    assert result is not None and result["passed"]
    assert overlapping[0] is not None
    assert overlapping[0]["blocking_issues"][0]["code"] == "llm_provider_claim_in_progress"
    assert provider.calls == 1


def test_race_loser_rejects_winner_with_changed_input(
    harness: tuple[FakeDb, Provider],
) -> None:
    db, provider = harness
    first = invoke(db, {"locale": "en"})
    assert first is not None and first["passed"]
    db.race_constraint = "uq_ai_assistant_llm_executions_gateway_claim"
    original = Repository.list_llm_executions_for_plan
    calls = 0

    def race_lookup(self: Repository, identifier: uuid.UUID) -> list[Any]:
        nonlocal calls
        calls += 1
        return [] if calls == 1 else original(self, identifier)

    Repository.list_llm_executions_for_plan = race_lookup
    try:
        result = invoke(db, {"locale": "es"})
    finally:
        Repository.list_llm_executions_for_plan = original
    assert result is not None
    assert result["blocking_issues"][0]["code"] == "llm_provider_input_conflict"
    assert provider.calls == 1


def test_postgresql_runtime_claim_replay_and_duplicate_guard_roll_back() -> None:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                baseline = connection.execute(text("SELECT count(*) FROM ai.assistant_llm_executions")).scalar_one()
                organization_id = connection.execute(
                    text("SELECT id FROM core.organizations ORDER BY id LIMIT 1")
                ).scalar_one()
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    repository = AssistantRepository(db)
                    assistant, created = repository.create_assistant_definition(
                        assistant_key=f"provider-claim-test-{uuid.uuid4().hex}",
                        assistant_name="Provider claim validation",
                        organization_id=organization_id,
                        ownership_scope="organization",
                        data_origin="validation",
                    )
                    assert created
                    session = repository.create_assistant_session(
                        assistant_id=assistant.assistant_id,
                        execution_organization_id=organization_id,
                    )
                    retrieval = repository.create_assistant_retrieval_plan(
                        assistant_id=assistant.assistant_id,
                        assistant_session_id=session.assistant_session_id,
                        execution_organization_id=organization_id,
                        requested_query="test",
                    )
                    execution_plan = repository.create_assistant_retrieval_execution_plan(
                        retrieval_plan_id=retrieval.retrieval_plan_id,
                        assistant_id=assistant.assistant_id,
                        assistant_session_id=session.assistant_session_id,
                    )
                    search = repository.create_assistant_search_execution(
                        execution_plan_id=execution_plan.execution_plan_id,
                        retrieval_plan_id=retrieval.retrieval_plan_id,
                        assistant_id=assistant.assistant_id,
                        assistant_session_id=session.assistant_session_id,
                        search_query="test",
                        search_completed=True,
                    )
                    context = repository.create_context_package(
                        search_execution_id=search.search_execution_id,
                        assistant_id=assistant.assistant_id,
                    )
                    prompt = repository.create_prompt_package(
                        context_package_id=context.context_package_id,
                        assistant_id=assistant.assistant_id,
                        system_prompt="system",
                        assistant_instructions="instructions",
                        assembled_context="",
                        citation_section="",
                    )
                    plan = repository.create_llm_invocation_plan(
                        prompt_package_id=prompt.prompt_package_id,
                        assistant_id=assistant.assistant_id,
                    )
                    db.commit()
                    first = runtime.build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(plan.gateway_id),
                        organization_id=organization_id,
                        persist_snapshot=False,
                    )
                    replay = runtime.build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(plan.gateway_id),
                        organization_id=organization_id,
                        persist_snapshot=False,
                    )
                    assert first is not None and replay is not None
                    assert first["passed"] and replay["passed"]
                    assert first["llm_execution_id"] == replay["llm_execution_id"]
                    assert replay["idempotent_replay"] is True
                    with pytest.raises(IntegrityError), db.begin_nested():
                        repository.create_llm_execution(
                            gateway_id=plan.gateway_id,
                            prompt_package_id=prompt.prompt_package_id,
                            assistant_id=assistant.assistant_id,
                        )
                    assert (
                        connection.execute(
                            text("SELECT count(*) FROM ai.assistant_llm_executions WHERE gateway_id=:gateway_id"),
                            {"gateway_id": plan.gateway_id},
                        ).scalar_one()
                        == 1
                    )
            finally:
                outer.rollback()
            assert connection.execute(text("SELECT count(*) FROM ai.assistant_llm_executions")).scalar_one() == baseline
    finally:
        engine.dispose()
