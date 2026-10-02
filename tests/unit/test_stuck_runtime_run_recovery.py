from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantLlmExecution, AssistantRuntimeRun
from app.repositories.assistant import AssistantRepository
from app.services.assistant_llm_execution_runtime import build_assistant_llm_execution_runtime
from app.services.assistant_run_recovery_runtime import (
    attempt_chat_run_takeover,
    initialize_chat_run_claim,
    lock_current_provider_claim,
    mark_expired_provider_uncertain,
)


def _database_url() -> str:
    url = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("RUNTIME_POSTGRES_TEST_DATABASE_URL is required")
    return url


def _run(db: Session) -> tuple[AssistantRepository, AssistantRuntimeRun]:
    organization_id = db.execute(text("SELECT id FROM core.organizations ORDER BY id LIMIT 1")).scalar_one()
    repository = AssistantRepository(db)
    assistant, _ = repository.create_assistant_definition(
        assistant_key=f"run-recovery-{uuid.uuid4().hex}",
        assistant_name="RuntimeRun recovery validation",
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="validation",
    )
    session = repository.create_assistant_session(
        assistant_id=assistant.assistant_id,
        execution_organization_id=organization_id,
    )
    run = repository.create_assistant_runtime_run(
        assistant_id=assistant.assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
        requested_query="test",
    )
    return repository, run


def _llm_plan(repository: AssistantRepository, run: AssistantRuntimeRun):
    retrieval = repository.create_assistant_retrieval_plan(
        assistant_id=run.assistant_id,
        assistant_session_id=run.assistant_session_id,
        execution_organization_id=run.organization_id,
        requested_query="test",
    )
    execution_plan = repository.create_assistant_retrieval_execution_plan(
        retrieval_plan_id=retrieval.retrieval_plan_id,
        assistant_id=run.assistant_id,
        assistant_session_id=run.assistant_session_id,
    )
    search = repository.create_assistant_search_execution(
        execution_plan_id=execution_plan.execution_plan_id,
        retrieval_plan_id=retrieval.retrieval_plan_id,
        assistant_id=run.assistant_id,
        assistant_session_id=run.assistant_session_id,
        search_query="test",
        search_completed=True,
    )
    context = repository.create_context_package(
        search_execution_id=search.search_execution_id,
        assistant_id=run.assistant_id,
    )
    prompt = repository.create_prompt_package(
        context_package_id=context.context_package_id,
        assistant_id=run.assistant_id,
        system_prompt="system",
        assistant_instructions="instructions",
        assembled_context="",
        citation_section="",
    )
    return repository.create_llm_invocation_plan(
        prompt_package_id=prompt.prompt_package_id,
        assistant_id=run.assistant_id,
    )


def test_postgresql_claim_takeover_fencing_and_legacy_roll_back() -> None:
    engine = create_engine(_database_url())
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    repository, run = _run(db)
                    legacy_repository, legacy = _run(db)
                    assert legacy_repository is not None
                    db.commit()
                    assert legacy.recovery_state is None
                    assert legacy.recovery_owner is None
                    assert legacy.recovery_generation is None
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=legacy.assistant_run_id,
                            organization_id=legacy.organization_id,
                            assistant_id=legacy.assistant_id,
                            assistant_session_id=legacy.assistant_session_id,
                        )
                        is None
                    )
                    generation = initialize_chat_run_claim(db, run)
                    db.commit()
                    assert generation == 1
                    assert run.recovery_state == "claimed"
                    assert run.recovery_owner is not None
                    assert run.recovery_lease_expires_at is not None
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        is None
                    )
                    db.execute(
                        text(
                            "UPDATE ai.assistant_runtime_runs "
                            "SET recovery_lease_expires_at=clock_timestamp()-interval '1 second' "
                            "WHERE assistant_run_id=:run_id"
                        ),
                        {"run_id": run.assistant_run_id},
                    )
                    db.commit()
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=uuid.uuid4(),
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        is None
                    )
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=uuid.uuid4(),
                            assistant_session_id=run.assistant_session_id,
                        )
                        is None
                    )
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=uuid.uuid4(),
                        )
                        is None
                    )
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        == 2
                    )
                    db.commit()
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        is None
                    )
                    assert not lock_current_provider_claim(
                        db,
                        run_id=run.assistant_run_id,
                        organization_id=run.organization_id,
                        assistant_id=run.assistant_id,
                        assistant_session_id=run.assistant_session_id,
                        generation=1,
                    )
                    assert lock_current_provider_claim(
                        db,
                        run_id=run.assistant_run_id,
                        organization_id=run.organization_id,
                        assistant_id=run.assistant_id,
                        assistant_session_id=run.assistant_session_id,
                        generation=2,
                    )
                    db.commit()
                    assert repository.get_assistant_runtime_run(run.assistant_run_id).recovery_generation == 2
            finally:
                outer.rollback()
    finally:
        engine.dispose()


def test_postgresql_pre_provider_claim_resumes_once_without_second_provider_claim() -> None:
    engine = create_engine(_database_url())
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    repository, run = _run(db)
                    plan = _llm_plan(repository, run)
                    assert initialize_chat_run_claim(db, run) == 1
                    db.commit()
                    metadata = {"assistant_run_id": str(run.assistant_run_id), "locale": "en"}
                    stale = build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(plan.gateway_id),
                        organization_id=run.organization_id,
                        request_payload_metadata=metadata,
                        runtime_run_claim_generation=0,
                        persist_snapshot=False,
                    )
                    assert stale is not None
                    assert stale["blocking_issues"][0]["code"] == "runtime_run_claim_stale"
                    assert len(repository.list_llm_executions_for_plan(plan.gateway_id)) == 1
                    assert repository.list_llm_executions_for_plan(plan.gateway_id)[0].provider_call_started_at is None
                    db.execute(
                        text(
                            "UPDATE ai.assistant_runtime_runs "
                            "SET recovery_lease_expires_at=clock_timestamp()-interval '1 second' "
                            "WHERE assistant_run_id=:run_id"
                        ),
                        {"run_id": run.assistant_run_id},
                    )
                    db.commit()
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        == 2
                    )
                    db.commit()
                    resumed = build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(plan.gateway_id),
                        organization_id=run.organization_id,
                        request_payload_metadata=metadata,
                        runtime_run_claim_generation=2,
                        resume_prepared_claim=True,
                        persist_snapshot=False,
                    )
                    assert resumed is not None and resumed["passed"]
                    assert resumed["execution_status"] == "completed"
                    assert resumed["provider_called"] is True
                    rows = repository.list_llm_executions_for_plan(plan.gateway_id)
                    assert len(rows) == 1
                    assert rows[0].provider_call_started_at is not None
                    assert rows[0].provider_call_finished_at is not None
                    assert rows[0].raw_output_text is not None
                    replay = build_assistant_llm_execution_runtime(
                        db,
                        gateway_id=str(plan.gateway_id),
                        organization_id=run.organization_id,
                        request_payload_metadata=metadata,
                        runtime_run_claim_generation=2,
                        persist_snapshot=False,
                    )
                    assert replay is not None and replay["idempotent_replay"]
                    second_plan = repository.create_llm_invocation_plan(
                        prompt_package_id=plan.prompt_package_id,
                        assistant_id=run.assistant_id,
                    )
                    db.commit()
                    with pytest.raises(IntegrityError), db.begin_nested():
                        repository.create_llm_execution(
                            gateway_id=second_plan.gateway_id,
                            prompt_package_id=second_plan.prompt_package_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                            execution_status="prepared",
                            request_payload_metadata={"assistant_run_id": str(run.assistant_run_id)},
                        )
            finally:
                outer.rollback()
    finally:
        engine.dispose()


def test_postgresql_unknown_provider_outcome_is_persistently_blocked() -> None:
    engine = create_engine(_database_url())
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    repository, run = _run(db)
                    plan = _llm_plan(repository, run)
                    initialize_chat_run_claim(db, run)
                    execution = repository.create_llm_execution(
                        gateway_id=plan.gateway_id,
                        prompt_package_id=plan.prompt_package_id,
                        assistant_id=run.assistant_id,
                        assistant_session_id=run.assistant_session_id,
                        execution_status="running",
                        request_payload_metadata={"assistant_run_id": str(run.assistant_run_id)},
                    )
                    execution.provider_call_started_at = db.scalar(text("SELECT clock_timestamp()"))
                    db.add(execution)
                    db.commit()
                    db.execute(
                        text(
                            "UPDATE ai.assistant_runtime_runs "
                            "SET recovery_lease_expires_at=clock_timestamp()-interval '1 second' "
                            "WHERE assistant_run_id=:run_id"
                        ),
                        {"run_id": run.assistant_run_id},
                    )
                    db.commit()
                    assert mark_expired_provider_uncertain(
                        db,
                        run_id=run.assistant_run_id,
                        organization_id=run.organization_id,
                        assistant_id=run.assistant_id,
                        assistant_session_id=run.assistant_session_id,
                    )
                    db.commit()
                    db.refresh(run)
                    assert run.recovery_state == "uncertain"
                    assert run.run_status == "blocked"
                    assert run.recovery_owner is None
                    assert run.recovery_lease_expires_at is None
                    assert run.failure_reason is not None
                    assert (
                        attempt_chat_run_takeover(
                            db,
                            run_id=run.assistant_run_id,
                            organization_id=run.organization_id,
                            assistant_id=run.assistant_id,
                            assistant_session_id=run.assistant_session_id,
                        )
                        is None
                    )
                    assert not lock_current_provider_claim(
                        db,
                        run_id=run.assistant_run_id,
                        organization_id=run.organization_id,
                        assistant_id=run.assistant_id,
                        assistant_session_id=run.assistant_session_id,
                        generation=1,
                    )
                    assert db.get(AssistantLlmExecution, execution.llm_execution_id).provider_call_finished_at is None
            finally:
                outer.rollback()
    finally:
        engine.dispose()
