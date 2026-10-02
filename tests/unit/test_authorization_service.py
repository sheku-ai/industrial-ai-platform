from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.api.dependencies import runtime_context
from app.api.dependencies.runtime_context import get_runtime_context
from app.identity.contracts import AuthenticatedPrincipal
from app.identity.models import AuthSession, IdentityUser
from app.security.resource_scope import ResourceScope, ResourceScopeInvariantError
from app.services.authorization import AuthorizationService


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalars:
    def all(self):
        return []


class _Session:
    def execute(self, statement):
        self.statement = statement
        return _Rows([("platform.security", "read")])

    def scalars(self, statement):
        self.policy_statement = statement
        return _Scalars()


def test_platform_role_assignment_grants_platform_security_read() -> None:
    session = _Session()

    permissions = AuthorizationService(session).resolve_permissions_for_scope(
        principal_id="reference-platform-operator",
        principal_type="reference_principal",
        resource_scope=ResourceScope.platform(),
    )

    assert "platform.security:read" in permissions


def test_runtime_context_uses_actor_reference_as_principal_id(monkeypatch) -> None:
    captured: dict[str, str | None] = {}
    now = datetime.now(UTC)
    user = IdentityUser(
        id=uuid4(),
        email_normalized="platform-operator@example.test",
        email_display="Platform Operator@example.test",
        status="active",
        must_change_password=False,
    )
    principal = AuthenticatedPrincipal(
        user=user,
        session=AuthSession(
            id=uuid4(),
            user_id=user.id,
            token_hash="a" * 64,
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=8),
            idle_timeout_seconds=3600,
            policy_version=1,
            updated_at=now,
            metadata_json={},
        ),
        memberships=(),
    )
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/test-runtime-context",
            "raw_path": b"/test-runtime-context",
            "query_string": b"",
            "headers": [(b"x-actor-reference", b"attacker-controlled")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )
    request.state.correlation_id = "test-correlation-id"

    class _AuthorizationService:
        def __init__(self, session):
            self.session = session

        def resolve_permissions_for_scope(
            self,
            *,
            resource_scope,
            principal_id,
            principal_type,
            allowed_role_ids,
        ):
            del allowed_role_ids
            captured["scope_type"] = resource_scope.scope_type.value
            captured["scope_id"] = resource_scope.scope_id
            captured["principal_id"] = principal_id
            captured["principal_type"] = principal_type
            return {"platform.security:read"}

    monkeypatch.setattr(runtime_context, "AuthorizationService", _AuthorizationService)

    context = get_runtime_context(
        request=request,
        x_authorization_scope="platform",
        x_organization_id=None,
        principal=principal,
        db=object(),
    )

    assert captured == {
        "scope_type": "platform",
        "scope_id": "platform",
        "principal_id": principal.actor_reference,
        "principal_type": "user",
    }
    assert context.actor_reference == principal.actor_reference
    assert context.actor_reference != request.headers["X-Actor-Reference"]
    assert context.scope_type == "platform"
    assert context.organization_id is None
    assert context.correlation_id == "test-correlation-id"
    assert context.has_permission("platform.security", "read") is True


def test_resource_scope_id_returns_authoritative_identifiers() -> None:
    organization_id = uuid4()

    assert ResourceScope.platform().scope_id == "platform"
    assert ResourceScope.organization(organization_id).scope_id == str(organization_id)
    assert ResourceScope.workload(organization_id, resource_id="workload-1").scope_id == "workload-1"


def test_resource_scope_rejects_missing_or_invalid_identifiers() -> None:
    with pytest.raises(ValueError, match="require an organization"):
        ResourceScope.organization(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="require a workload resource identifier"):
        ResourceScope.workload(uuid4(), resource_id=None)


def test_resource_scope_id_fails_closed_if_an_invariant_is_corrupted() -> None:
    scope = ResourceScope.workload(uuid4(), resource_id="workload-1")
    object.__setattr__(scope, "resource_id", None)

    with pytest.raises(ResourceScopeInvariantError, match="workload resource identifier"):
        _ = scope.scope_id
