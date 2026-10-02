from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantContextPackage,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantSearchExecution,
)
from app.repositories.assistant import AssistantRepository


class MemorySession:
    def __init__(self, rows: dict[type, dict[uuid.UUID, object]]) -> None:
        self.rows = rows
        self.added: list[object] = []

    def get(self, model: type, identifier: uuid.UUID) -> object | None:
        return self.rows.get(model, {}).get(identifier)

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        return None


def parent(model: type, **overrides: object) -> SimpleNamespace:
    fields = {
        "assistant_id": uuid.uuid4(),
        "assistant_session_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "ownership_scope": "organization",
        "data_origin": "operational",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_context_inherits_persisted_search_session_and_rejects_other_session() -> None:
    search_id = uuid.uuid4()
    search = parent(AssistantSearchExecution)
    db = MemorySession({AssistantSearchExecution: {search_id: search}})
    repository = AssistantRepository(db)

    context = repository.create_context_package(
        search_execution_id=search_id,
        assistant_id=search.assistant_id,
        assistant_session_id=search.assistant_session_id,
    )
    assert context.organization_id == search.organization_id
    assert context.assistant_session_id == search.assistant_session_id

    with pytest.raises(ValueError, match="session lineage"):
        repository.create_context_package(
            search_execution_id=search_id,
            assistant_id=search.assistant_id,
            assistant_session_id=uuid.uuid4(),
        )


def test_prompt_and_invocation_plan_inherit_exact_parent_lineage() -> None:
    context_id = uuid.uuid4()
    context = parent(AssistantContextPackage)
    db = MemorySession({AssistantContextPackage: {context_id: context}})
    repository = AssistantRepository(db)

    prompt = repository.create_prompt_package(
        context_package_id=context_id,
        assistant_id=context.assistant_id,
        system_prompt="system",
        assistant_instructions="instructions",
        assembled_context="context",
        citation_section="citations",
    )
    assert prompt.assistant_session_id == context.assistant_session_id
    assert prompt.organization_id == context.organization_id

    prompt_id = prompt.prompt_package_id
    db.rows[AssistantPromptPackage] = {prompt_id: prompt}
    plan = repository.create_llm_invocation_plan(
        prompt_package_id=prompt_id,
        assistant_id=prompt.assistant_id,
    )
    assert plan.assistant_session_id == context.assistant_session_id
    assert plan.organization_id == context.organization_id


def test_llm_execution_rejects_wrong_session_and_inherits_plan_scope() -> None:
    gateway_id = uuid.uuid4()
    plan = parent(AssistantLlmInvocationPlan, prompt_package_id=uuid.uuid4())
    db = MemorySession({AssistantLlmInvocationPlan: {gateway_id: plan}})
    repository = AssistantRepository(db)

    with pytest.raises(ValueError, match="session lineage"):
        repository.create_llm_execution(
            gateway_id=gateway_id,
            prompt_package_id=plan.prompt_package_id,
            assistant_id=plan.assistant_id,
            assistant_session_id=uuid.uuid4(),
        )

    execution = repository.create_llm_execution(
        gateway_id=gateway_id,
        prompt_package_id=plan.prompt_package_id,
        assistant_id=plan.assistant_id,
    )
    assert execution.assistant_session_id == plan.assistant_session_id
    assert execution.organization_id == plan.organization_id


def test_citation_and_response_require_one_exact_lineage() -> None:
    execution_id = uuid.uuid4()
    prompt_id = uuid.uuid4()
    context_id = uuid.uuid4()
    execution = parent(AssistantLlmExecution, prompt_package_id=prompt_id)
    prompt = parent(
        AssistantPromptPackage,
        context_package_id=context_id,
        assistant_id=execution.assistant_id,
        assistant_session_id=execution.assistant_session_id,
        organization_id=execution.organization_id,
    )
    context = parent(
        AssistantContextPackage,
        assistant_id=execution.assistant_id,
        assistant_session_id=execution.assistant_session_id,
        organization_id=execution.organization_id,
    )
    db = MemorySession(
        {
            AssistantLlmExecution: {execution_id: execution},
            AssistantPromptPackage: {prompt_id: prompt},
            AssistantContextPackage: {context_id: context},
        }
    )
    repository = AssistantRepository(db)
    citation = repository.create_citation_verification(
        llm_execution_id=execution_id,
        prompt_package_id=prompt_id,
        context_package_id=context_id,
    )
    citation_id = citation.citation_verification_id
    db.rows[AssistantCitationVerification] = {citation_id: citation}

    with pytest.raises(ValueError, match="session lineage"):
        repository.create_assistant_response(
            citation_verification_id=citation_id,
            llm_execution_id=execution_id,
            prompt_package_id=prompt_id,
            context_package_id=context_id,
            assistant_id=execution.assistant_id,
            assistant_session_id=uuid.uuid4(),
            response_text="answer",
        )

    response = repository.create_assistant_response(
        citation_verification_id=citation_id,
        llm_execution_id=execution_id,
        prompt_package_id=prompt_id,
        context_package_id=context_id,
        assistant_id=execution.assistant_id,
        assistant_session_id=execution.assistant_session_id,
        response_text="answer",
    )
    assert response.organization_id == execution.organization_id
    assert response.assistant_session_id == execution.assistant_session_id


def test_downstream_models_keep_simple_foreign_keys_and_add_scoped_constraints() -> None:
    expected = {
        AssistantContextPackage: (
            "uq_ai_assistant_context_packages_lineage",
            "fk_ai_assistant_context_packages_scoped_search",
            "ai.assistant_search_executions.search_execution_id",
        ),
        AssistantPromptPackage: (
            "uq_ai_assistant_prompt_packages_lineage",
            "fk_ai_assistant_prompt_packages_scoped_context",
            "ai.assistant_context_packages.context_package_id",
        ),
        AssistantLlmInvocationPlan: (
            "uq_ai_assistant_llm_invocation_plans_lineage",
            "fk_ai_assistant_llm_invocation_plans_scoped_prompt",
            "ai.assistant_prompt_packages.prompt_package_id",
        ),
    }
    for model, (unique_name, scoped_fk, simple_target) in expected.items():
        names = {constraint.name for constraint in model.__table__.constraints}
        assert unique_name in names
        assert scoped_fk in names
        foreign_keys = {
            element.target_fullname
            for constraint in model.__table__.constraints
            if hasattr(constraint, "elements")
            for element in constraint.elements
        }
        assert simple_target in foreign_keys


def test_migration_is_chained_and_fails_closed_without_data_repair() -> None:
    migration = Path(
        "apps/api/alembic/versions/20260923_2820_assistant_downstream_authoritative_lineage.py"
    ).read_text()
    assert 'down_revision: str | Sequence[str] | None = "20260923_2810"' in migration
    assert "raise RuntimeError" in migration
    assert "UPDATE ai." not in migration
    assert "DELETE FROM ai." not in migration
    assert "DEFERRABLE INITIALLY DEFERRED" in migration
    assert "assistant_citation_verifications" in migration
    assert "assistant_responses" in migration
