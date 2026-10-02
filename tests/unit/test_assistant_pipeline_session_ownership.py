from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.models.assistant_runtime import (
    AssistantRetrievalExecutionPlan,
    AssistantRetrievalPlan,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
)
from app.repositories.assistant import AssistantRepository
from app.services import assistant_runtime, assistant_search_execution_gateway, assistant_search_execution_runtime

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apps/api/alembic/versions/20260923_2810_assistant_pipeline_session_ownership.py"
)


class _Persistence:
    def __init__(self, parent: Any | None = None) -> None:
        self.parent = parent
        self.added: list[Any] = []

    def get(self, _model: Any, _identifier: uuid.UUID) -> Any | None:
        return self.parent

    def add(self, record: Any) -> None:
        self.added.append(record)

    def flush(self) -> None:
        pass


def _ownership(organization_id: uuid.UUID | None, *, scope: str = "organization") -> dict[str, Any]:
    return {"organization_id": organization_id, "ownership_scope": scope, "data_origin": "operational"}


def test_run_and_retrieval_plan_accept_matching_session(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session = SimpleNamespace(
        assistant_session_id=uuid.uuid4(), assistant_id=assistant_id, **_ownership(organization_id)
    )
    persistence = _Persistence()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))
    monkeypatch.setattr(repository, "_session_for_ownership", lambda *args: session)

    run = repository.create_assistant_runtime_run(
        assistant_id=assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
    )
    plan = repository.create_assistant_retrieval_plan(
        assistant_id=assistant_id,
        assistant_session_id=session.assistant_session_id,
        execution_organization_id=organization_id,
    )

    assert persistence.added == [run, plan]
    assert run.organization_id == plan.organization_id == organization_id
    assert run.assistant_session_id == plan.assistant_session_id == session.assistant_session_id


@pytest.mark.parametrize("method", ["create_assistant_runtime_run", "create_assistant_retrieval_plan"])
def test_run_and_plan_reject_cross_organization_session_before_persistence(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    organization_id = uuid.uuid4()
    persistence = _Persistence()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))
    monkeypatch.setattr(repository, "_session_for_ownership", lambda *args: None)

    with pytest.raises(ValueError, match="assistant session not found"):
        getattr(repository, method)(
            assistant_id=uuid.uuid4(),
            assistant_session_id=uuid.uuid4(),
            execution_organization_id=organization_id,
        )

    assert persistence.added == []


@pytest.mark.parametrize("method", ["create_assistant_runtime_run", "create_assistant_retrieval_plan"])
def test_run_and_plan_reject_other_assistant_in_same_organization(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    organization_id = uuid.uuid4()
    session = SimpleNamespace(assistant_id=uuid.uuid4(), **_ownership(organization_id))
    persistence = _Persistence()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))
    monkeypatch.setattr(repository, "_session_for_ownership", lambda *args: session)

    with pytest.raises(ValueError, match="assistant lineage is inconsistent"):
        getattr(repository, method)(
            assistant_id=uuid.uuid4(),
            assistant_session_id=uuid.uuid4(),
            execution_organization_id=organization_id,
        )

    assert persistence.added == []


def test_legacy_session_is_not_promoted_to_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    legacy = SimpleNamespace(assistant_id=uuid.uuid4(), **_ownership(None, scope="legacy_unscoped"))
    persistence = _Persistence()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))
    monkeypatch.setattr(repository, "_session_for_ownership", lambda *args: legacy)

    with pytest.raises(ValueError, match="ownership lineage is inconsistent"):
        repository.create_assistant_retrieval_plan(
            assistant_id=legacy.assistant_id,
            assistant_session_id=uuid.uuid4(),
            execution_organization_id=organization_id,
        )

    assert legacy.organization_id is None
    assert persistence.added == []


def test_global_assistant_session_still_creates_global_run(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant_id = uuid.uuid4()
    session = SimpleNamespace(assistant_id=assistant_id, **_ownership(None, scope="global"))
    persistence = _Persistence()
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(
        repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(None, scope="global")
    )
    monkeypatch.setattr(repository, "_session_for_ownership", lambda *args: session)

    run = repository.create_assistant_runtime_run(assistant_id=assistant_id, assistant_session_id=uuid.uuid4())

    assert persistence.added == [run]
    assert run.organization_id is None
    assert run.ownership_scope == "global"


def test_retrieval_execution_requires_exact_parent_session(monkeypatch: pytest.MonkeyPatch) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    parent = SimpleNamespace(
        retrieval_plan_id=uuid.uuid4(),
        assistant_id=assistant_id,
        assistant_session_id=uuid.uuid4(),
        **_ownership(organization_id),
    )
    persistence = _Persistence(parent)
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))

    with pytest.raises(ValueError, match="assistant session lineage is inconsistent"):
        repository.create_assistant_retrieval_execution_plan(
            retrieval_plan_id=parent.retrieval_plan_id,
            assistant_id=assistant_id,
            assistant_session_id=uuid.uuid4(),
        )
    assert persistence.added == []

    execution = repository.create_assistant_retrieval_execution_plan(
        retrieval_plan_id=parent.retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=parent.assistant_session_id,
    )
    assert execution.assistant_session_id == parent.assistant_session_id
    assert execution.organization_id == organization_id


def test_search_execution_requires_exact_execution_session_and_retrieval_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    parent = SimpleNamespace(
        execution_plan_id=uuid.uuid4(),
        retrieval_plan_id=uuid.uuid4(),
        assistant_id=assistant_id,
        assistant_session_id=uuid.uuid4(),
        **_ownership(organization_id),
    )
    persistence = _Persistence(parent)
    repository = AssistantRepository(persistence)  # type: ignore[arg-type]
    monkeypatch.setattr(repository, "_ownership_for_assistant", lambda *args, **kwargs: _ownership(organization_id))

    with pytest.raises(ValueError, match="assistant session lineage is inconsistent"):
        repository.create_assistant_search_execution(
            execution_plan_id=parent.execution_plan_id,
            retrieval_plan_id=parent.retrieval_plan_id,
            assistant_id=assistant_id,
            assistant_session_id=uuid.uuid4(),
            search_query="inspection",
            search_completed=True,
        )
    with pytest.raises(ValueError, match="retrieval lineage is inconsistent"):
        repository.create_assistant_search_execution(
            execution_plan_id=parent.execution_plan_id,
            retrieval_plan_id=uuid.uuid4(),
            assistant_id=assistant_id,
            assistant_session_id=parent.assistant_session_id,
            search_query="inspection",
            search_completed=True,
        )
    assert persistence.added == []

    search = repository.create_assistant_search_execution(
        execution_plan_id=parent.execution_plan_id,
        retrieval_plan_id=parent.retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=parent.assistant_session_id,
        search_query="inspection",
        search_completed=True,
    )
    assert search.assistant_session_id == parent.assistant_session_id
    assert search.retrieval_plan_id == parent.retrieval_plan_id


def test_direct_run_runtime_does_not_read_cross_organization_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()

    class _ScopedRepository:
        def __init__(self, _db: Any) -> None:
            pass

        def get_scoped_assistant_definition(self, _id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
            return SimpleNamespace(assistant_id=assistant_id)

        def get_scoped_assistant_session(self, _id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
            return None

    monkeypatch.setattr(assistant_runtime, "AssistantRepository", _ScopedRepository)
    result = assistant_runtime.build_assistant_run_runtime(
        object(),
        assistant_id=str(assistant_id),
        assistant_session_id=str(uuid.uuid4()),
        organization_id=organization_id,
        persist_snapshot=False,
    )
    assert result is None


@pytest.mark.parametrize("location", ["organization_id", "filters"])
def test_search_gateway_rejects_conflicting_organization_config(monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    organization_id = uuid.uuid4()
    execution = SimpleNamespace(
        execution_plan_id=uuid.uuid4(),
        retrieval_plan_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        assistant_session_id=uuid.uuid4(),
        execution_status="prepared",
        execution_state="readiness_only",
        selected_search_mode="enterprise_search",
        selected_runtime_domain="enterprise_search",
        retrieval_executed=False,
        **_ownership(organization_id),
    )
    plan = SimpleNamespace(
        retrieval_plan_id=execution.retrieval_plan_id,
        assistant_id=execution.assistant_id,
        assistant_session_id=execution.assistant_session_id,
        requested_query="inspection",
        **_ownership(organization_id),
    )

    class _Repository:
        def __init__(self, _db: Any) -> None:
            pass

        def get_scoped_artifact(self, model: Any, *_args: Any, **_kwargs: Any) -> Any:
            return execution if model is AssistantRetrievalExecutionPlan else plan

    monkeypatch.setattr(assistant_search_execution_gateway, "AssistantRepository", _Repository)
    search_config = (
        {"organization_id": str(uuid.uuid4())}
        if location == "organization_id"
        else {"filters": {"organization_id": str(uuid.uuid4())}}
    )
    result = assistant_search_execution_gateway.build_assistant_search_execution_gateway(
        object(),
        execution_plan_id=str(execution.execution_plan_id),
        organization_id=organization_id,
        search_config=search_config,
    )
    assert "search_organization_scope_mismatch" in {item["code"] for item in result["blocking_issues"]}


def test_search_config_uses_persisted_organization_for_missing_or_matching_scope() -> None:
    organization_id = uuid.uuid4()
    for supplied in (
        {},
        {"organization_id": str(organization_id), "filters": {"organization_id": str(organization_id)}},
    ):
        scoped = assistant_search_execution_runtime._scoped_search_config(
            supplied, {"organization_id": str(uuid.uuid4())}, organization_id=organization_id
        )
        assert scoped["organization_id"] == str(organization_id)
        assert scoped["filters"]["organization_id"] == str(organization_id)


def test_search_runtime_sends_persisted_organization_to_enterprise_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    plan = SimpleNamespace(
        retrieval_plan_id=uuid.uuid4(),
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        requested_query="inspection",
        runtime_metadata={"organization_id": str(uuid.uuid4())},
        **_ownership(organization_id),
    )
    execution = SimpleNamespace(
        execution_plan_id=uuid.uuid4(),
        retrieval_plan_id=plan.retrieval_plan_id,
        assistant_id=assistant_id,
        assistant_session_id=session_id,
        **_ownership(organization_id),
    )
    assistant = SimpleNamespace(assistant_id=assistant_id)
    session = SimpleNamespace(assistant_session_id=session_id, assistant_id=assistant_id)

    class _Repository:
        def __init__(self, _db: Any) -> None:
            pass

        def get_scoped_artifact(self, model: Any, *_args: Any, **_kwargs: Any) -> Any:
            return execution if model is AssistantRetrievalExecutionPlan else plan

        def get_scoped_assistant_definition(self, *_args: Any, **_kwargs: Any) -> Any:
            return assistant

        def get_scoped_assistant_session(self, *_args: Any, **_kwargs: Any) -> Any:
            return session

    captured: list[dict[str, Any]] = []

    def _search(**kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs["search_config"])
        return {
            "blocking_issues": [{"code": "synthetic_search_block", "severity": "blocking"}],
            "search_completed": False,
            "result_count": 0,
            "search_uses_postgresql_fts": True,
            "warnings": [],
        }

    monkeypatch.setattr(assistant_search_execution_runtime, "AssistantRepository", _Repository)
    monkeypatch.setattr(
        assistant_search_execution_runtime,
        "build_assistant_search_execution_gateway",
        lambda *a, **k: {"blocking_issues": [], "warnings": []},
    )
    monkeypatch.setattr(assistant_search_execution_runtime, "build_enterprise_search", _search)
    for serializer in (
        "assistant_to_dict",
        "assistant_session_to_dict",
        "assistant_retrieval_plan_to_dict",
        "assistant_retrieval_execution_plan_to_dict",
    ):
        monkeypatch.setattr(assistant_search_execution_runtime, serializer, lambda _record: {})

    result = assistant_search_execution_runtime.build_assistant_search_execution_runtime(
        object(),
        execution_plan_id=str(execution.execution_plan_id),
        organization_id=organization_id,
        search_config={},
        persist_snapshot=False,
    )

    assert result is not None and result["passed"] is False
    assert captured == [{"filters": {"organization_id": str(organization_id)}, "organization_id": str(organization_id)}]


def test_model_defines_scoped_foreign_keys_and_preserves_simple_foreign_keys() -> None:
    expected = {
        AssistantRuntimeRun: "fk_ai_assistant_runtime_runs_scoped_session",
        AssistantRetrievalPlan: "fk_ai_assistant_retrieval_plans_scoped_session",
        AssistantRetrievalExecutionPlan: "fk_ai_assistant_retrieval_execution_plans_scoped_plan",
        AssistantSearchExecution: "fk_ai_assistant_search_executions_scoped_execution",
    }
    for model, name in expected.items():
        constraints = model.__table__.constraints
        assert any(isinstance(item, ForeignKeyConstraint) and item.name == name for item in constraints)
        assert any(isinstance(item, ForeignKeyConstraint) and len(item.elements) == 1 for item in constraints)
    assert any(
        isinstance(item, UniqueConstraint) and item.name == "uq_ai_assistant_sessions_id_assistant_organization"
        for item in AssistantSession.__table__.constraints
    )


def test_migration_preserves_simple_foreign_keys_and_checks_historical_lineage() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "20260923_2800"' in source
    assert "fk_ai_assistant_runtime_runs_scoped_session" in source
    assert "fk_ai_assistant_retrieval_plans_scoped_session" in source
    assert "fk_ai_assistant_retrieval_execution_plans_scoped_plan" in source
    assert "fk_ai_assistant_search_executions_scoped_execution" in source
    assert "IS NOT DISTINCT FROM NEW.assistant_session_id" in source
    assert "Resolve it through a governed process" in source
    assert "drop_constraint" in source
    assert "UPDATE ai." not in source
