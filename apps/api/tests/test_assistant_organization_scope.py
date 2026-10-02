import uuid
from types import SimpleNamespace

import pytest

from app.models.assistant_runtime import AssistantDefinition, AssistantSearchExecution, AssistantSession
from app.repositories.assistant import AssistantRepository


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        return None

    def scalars(self, statement):
        self.statement = statement
        return _EmptyScalars()


def _sql(session: _CapturingSession) -> str:
    assert session.statement is not None
    return str(session.statement.compile(compile_kwargs={"literal_binds": True}))


def test_scoped_assistant_read_allows_only_explicit_global_or_matching_organization() -> None:
    organization_id = uuid.uuid4()
    session = _CapturingSession()

    AssistantRepository(session).get_scoped_assistant_definition(uuid.uuid4(), organization_id=organization_id)

    statement = _sql(session)
    assert "ownership_scope = 'global'" in statement
    assert "ownership_scope = 'organization'" in statement
    assert f"organization_id = '{organization_id.hex}'" in statement
    assert "legacy_unscoped" not in statement


def test_platform_assistant_listing_excludes_legacy_unscoped_records() -> None:
    session = _CapturingSession()

    AssistantRepository(session).list_scoped_assistant_definitions(organization_id=None, platform_scope=True)

    assert "ownership_scope != 'legacy_unscoped'" in _sql(session)


def test_conversation_listing_requires_matching_organization_and_owned_scope() -> None:
    organization_id = uuid.uuid4()
    session = _CapturingSession()

    AssistantRepository(session).list_scoped_conversations(organization_id=organization_id)

    statement = _sql(session)
    assert f"organization_id = '{organization_id.hex}'" in statement
    assert "ownership_scope = 'organization'" in statement


def test_deep_artifact_query_filters_scope_in_sql() -> None:
    organization_id = uuid.uuid4()
    session = _CapturingSession()

    AssistantRepository(session).get_scoped_artifact(
        AssistantSearchExecution,
        AssistantSearchExecution.search_execution_id,
        uuid.uuid4(),
        organization_id=organization_id,
    )

    statement = _sql(session)
    assert "ownership_scope = 'global'" in statement
    assert "ownership_scope = 'organization'" in statement
    assert f"organization_id = '{organization_id.hex}'" in statement


class _LineageSession:
    def __init__(self, assistant, search_execution) -> None:
        self.assistant = assistant
        self.search_execution = search_execution
        self.added = None

    def get(self, model, identifier):
        if model is AssistantDefinition:
            return self.assistant
        if model is AssistantSearchExecution:
            return self.search_execution
        return None

    def add(self, record) -> None:
        self.added = record

    def flush(self) -> None:
        return None


def test_context_package_inherits_authoritative_ownership() -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="validation",
    )
    search = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="validation",
    )
    session = _LineageSession(assistant, search)

    record = AssistantRepository(session).create_context_package(
        search_execution_id=uuid.uuid4(),
        assistant_id=assistant_id,
    )

    assert record.organization_id == organization_id
    assert record.ownership_scope == "organization"
    assert record.data_origin == "validation"


def test_context_package_rejects_inconsistent_assistant_lineage() -> None:
    organization_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
    )
    search = SimpleNamespace(
        assistant_id=uuid.uuid4(),
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
    )

    with pytest.raises(ValueError, match="assistant lineage is inconsistent"):
        AssistantRepository(_LineageSession(assistant, search)).create_context_package(
            search_execution_id=uuid.uuid4(),
            assistant_id=assistant_id,
        )


def test_global_assistant_session_uses_authoritative_execution_organization() -> None:
    assistant_id = uuid.uuid4()
    authorized_organization_id = uuid.uuid4()
    manipulated_organization_id = uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=None,
        ownership_scope="global",
        data_origin="reference",
    )
    session = _LineageSession(assistant, None)

    record = AssistantRepository(session).create_assistant_session(
        assistant_id=assistant_id,
        execution_organization_id=authorized_organization_id,
        runtime_context={
            "organization_id": str(manipulated_organization_id),
            "validation_generated": True,
        },
    )

    assert record.organization_id == authorized_organization_id
    assert record.ownership_scope == "organization"
    assert record.data_origin == "validation"


class _GlobalAssistantRunSession:
    def __init__(self, assistant, assistant_session) -> None:
        self.assistant = assistant
        self.assistant_session = assistant_session

    def get(self, model, identifier):
        if model is AssistantDefinition:
            return self.assistant
        if model is AssistantSession:
            return self.assistant_session
        return None

    def add(self, record) -> None:
        return None

    def flush(self) -> None:
        return None


def test_global_assistant_run_inherits_organization_from_session() -> None:
    assistant_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    assistant_session_id = uuid.uuid4()
    assistant = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=None,
        ownership_scope="global",
        data_origin="reference",
    )
    assistant_session = SimpleNamespace(
        assistant_id=assistant_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="validation",
    )

    record = AssistantRepository(_GlobalAssistantRunSession(assistant, assistant_session)).create_assistant_runtime_run(
        assistant_id=assistant_id,
        assistant_session_id=assistant_session_id,
    )

    assert record.organization_id == organization_id
    assert record.ownership_scope == "organization"
    assert record.data_origin == "validation"
