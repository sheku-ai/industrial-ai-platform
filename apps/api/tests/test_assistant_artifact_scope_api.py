import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.authentication import require_api_access
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.repositories.assistant import AssistantRepository
from main import app

client = TestClient(app)


def _context(*, organization_id: uuid.UUID, permitted: bool = True) -> RuntimeRequestContext:
    permissions = (
        frozenset({"platform.assistants:read", "platform.assistants:administer"}) if permitted else frozenset()
    )
    return RuntimeRequestContext(
        scope_type="organization",
        organization_id=organization_id,
        actor_reference="artifact-scope-test",
        permissions=permissions,
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[require_api_access] = lambda: None
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_runtime_context, None)
    app.dependency_overrides.pop(require_api_access, None)


def test_deep_artifact_read_allows_authorized_organization(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id=organization_id)
    monkeypatch.setattr(
        AssistantRepository,
        "get_scoped_artifact",
        lambda *args, **kwargs: SimpleNamespace(organization_id=organization_id, ownership_scope="organization"),
    )
    monkeypatch.setattr(
        "app.api.routes.assistants.read_assistant_search_execution",
        lambda db, identifier: {"search_execution_id": identifier},
    )

    response = client.get(f"/api/assistants/search-executions/{artifact_id}")

    assert response.status_code == 200
    assert response.json()["search_execution_id"] == str(artifact_id)


def test_deep_artifact_read_hides_known_cross_organization_id(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id=organization_id)
    monkeypatch.setattr(AssistantRepository, "get_scoped_artifact", lambda *args, **kwargs: None)

    response = client.get(f"/api/assistants/search-executions/{artifact_id}")

    assert response.status_code == 404


def test_deep_artifact_read_denies_missing_permission(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(
        organization_id=organization_id,
        permitted=False,
    )
    monkeypatch.setattr(AssistantRepository, "get_scoped_artifact", lambda *args, **kwargs: None)

    response = client.get(f"/api/assistants/context-packages/{uuid.uuid4()}")

    assert response.status_code == 403


def test_legacy_unscoped_artifact_is_not_visible(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id=organization_id)
    monkeypatch.setattr(AssistantRepository, "get_scoped_artifact", lambda *args, **kwargs: None)

    response = client.get(f"/api/assistants/prompt-packages/{uuid.uuid4()}")

    assert response.status_code == 404


def test_technical_prompt_endpoint_redacts_internal_prompt_fields(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    app.dependency_overrides[get_runtime_context] = lambda: _context(organization_id=organization_id)
    monkeypatch.setattr(
        AssistantRepository,
        "get_scoped_artifact",
        lambda *args, **kwargs: SimpleNamespace(organization_id=organization_id, ownership_scope="organization"),
    )
    monkeypatch.setattr(
        "app.api.routes.assistants.read_assistant_prompt_package",
        lambda db, identifier: {
            "prompt_package_id": identifier,
            "system_prompt": "internal",
            "assistant_instructions": "internal",
            "assembled_context": "private context",
            "citation_section": "private citations",
            "prompt_metadata": {"safe": True},
        },
    )

    response = client.get(f"/api/assistants/prompt-packages/{artifact_id}")

    assert response.status_code == 200
    assert response.json() == {
        "prompt_package_id": str(artifact_id),
        "prompt_metadata": {"safe": True},
    }
