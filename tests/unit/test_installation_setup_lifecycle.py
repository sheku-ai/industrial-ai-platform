from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.routes.installation_setup import _authorized
from app.core.config import Settings
from app.services.installation_setup import (
    EVIDENCE_TYPES,
    InstallationSetupError,
    InstallationSetupService,
    InstallationState,
    _canonical_hash,
)


def _service() -> InstallationSetupService:
    return InstallationSetupService(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        Settings(),
    )


def _evidence(*types: str) -> dict[str, SimpleNamespace]:
    return {evidence_type: SimpleNamespace(evidence_payload={"type": evidence_type}) for evidence_type in types}


def test_state_is_derived_from_persisted_evidence() -> None:
    service = _service()
    setup = SimpleNamespace(setup_schema_version=1)

    assert service._status_payload(None, {}, None, include_details=False)["state"] == "UNCONFIGURED"
    assert (
        service._status_payload(
            setup,
            _evidence(EVIDENCE_TYPES[0]),
            None,
            include_details=False,
        )["state"]
        == "IN_PROGRESS"
    )
    ready = service._status_payload(
        setup,
        _evidence(*EVIDENCE_TYPES),
        None,
        include_details=True,
    )
    assert ready["state"] == "READY_TO_COMPLETE"
    assert ready["ready_to_complete"] is True
    assert ready["next_step"] == "complete"
    assert (
        service._status_payload(
            setup,
            _evidence(*EVIDENCE_TYPES),
            SimpleNamespace(),
            include_details=False,
        )["state"]
        == "COMPLETED"
    )


def test_completion_is_idempotent_when_evidence_already_exists() -> None:
    service = _service()
    setup = SimpleNamespace()
    service._ensure_setup = lambda: setup  # type: ignore[method-assign]
    service._lock = lambda: None  # type: ignore[method-assign]
    service._completion = lambda _setup: SimpleNamespace()  # type: ignore[method-assign]
    service.status = lambda **_kwargs: {"state": "COMPLETED"}  # type: ignore[method-assign]

    assert service.complete() == {"state": "COMPLETED"}


def test_setup_steps_are_immutable_after_completion() -> None:
    service = _service()
    service._completion = lambda _setup: SimpleNamespace()  # type: ignore[method-assign]

    with pytest.raises(InstallationSetupError) as captured:
        service._assert_mutable(SimpleNamespace())  # type: ignore[arg-type]

    assert captured.value.code == "INSTALLATION_ALREADY_COMPLETED"


def test_completion_requires_all_authoritative_evidence() -> None:
    with pytest.raises(InstallationSetupError) as captured:
        _service()._verified_resources(SimpleNamespace(), {})

    assert captured.value.code == "INSTALLATION_SETUP_NOT_READY"


def test_corrupt_evidence_resource_ids_fail_with_a_stable_error() -> None:
    evidence = _evidence(*EVIDENCE_TYPES)
    evidence["organization_configured"].organization_id = SimpleNamespace()
    evidence["administrator_configured"].resource_id = "not-a-uuid"
    evidence["administrator_configured"].evidence_payload = {"role_id": "not-a-uuid"}
    evidence["preferences_configured"].resource_id = "not-a-uuid"

    with pytest.raises(InstallationSetupError) as captured:
        _service()._verified_resources(SimpleNamespace(), evidence)  # type: ignore[arg-type]

    assert captured.value.code == "INSTALLATION_EVIDENCE_INCONSISTENT"


def test_evidence_reconciliation_is_idempotent_for_equivalent_payload() -> None:
    setup_id = SimpleNamespace()
    setup = SimpleNamespace(installation_setup_id=setup_id)
    payload = {"language": "en", "timezone": "UTC"}
    evidence_hash = _canonical_hash(
        {
            "evidence_type": "preferences_configured",
            "evidence_version": 1,
            "organization_id": None,
            "resource_type": "runtime_configuration_revision",
            "resource_id": "revision-1",
            "payload": payload,
        }
    )
    existing = SimpleNamespace(evidence_hash=evidence_hash, evidence_version=1)
    service = _service()
    service._evidence = lambda _setup: {  # type: ignore[method-assign]
        "preferences_configured": existing
    }

    reconciled = service._write_evidence(
        setup,  # type: ignore[arg-type]
        evidence_type="preferences_configured",
        organization_id=None,
        resource_type="runtime_configuration_revision",
        resource_id="revision-1",
        payload=payload,
    )

    assert reconciled is existing


def test_legacy_reconciliation_does_not_reopen_existing_setup() -> None:
    service = _service()
    service._current_setup = lambda: SimpleNamespace()  # type: ignore[method-assign]

    assert service.reconcile_legacy_bootstrap() is False


def test_canonical_evidence_hash_is_order_independent() -> None:
    assert _canonical_hash({"organization": "example", "version": 1}) == _canonical_hash(
        {"version": 1, "organization": "example"}
    )


def test_setup_token_must_be_explicitly_configured_and_match() -> None:
    assert _authorized("secret", Settings(sheku_setup_token="secret")) is True
    assert _authorized("wrong", Settings(sheku_setup_token="secret")) is False
    assert _authorized("", Settings(sheku_setup_token="")) is False


def test_portal_keeps_setup_token_in_component_memory() -> None:
    source = Path("apps/admin-portal/components/setup/InstallationWizard.tsx").read_text(encoding="utf-8")

    assert "useState('')" in source
    assert "X-SHEKU-Setup-Token" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "window.location.assign('/login')" in source


def test_portal_prevalidates_the_canonical_initial_admin_password_policy() -> None:
    source = Path("apps/admin-portal/components/setup/InstallationWizard.tsx").read_text(encoding="utf-8")
    api_source = Path("apps/admin-portal/lib/installation-setup-api.ts").read_text(encoding="utf-8")

    assert "password_policy" in api_source
    assert "passwordCharacterLength(password) < passwordMinLength" in source
    assert "passwordCharacterLength(password) > passwordMaxLength" in source
    assert "password !== passwordConfirmation" in source
    assert "passwordContainsContext(password, email" in source
    assert "PASSWORD_TOO_SHORT: 'setup.errors.passwordTooShort'" in source
    assert "PASSWORD_TOO_LONG: 'setup.errors.passwordTooLong'" in source
    assert "PASSWORD_CONTEXT_MATCH: 'setup.errors.passwordContext'" in source
    assert "PASSWORD_COMMON: 'setup.errors.passwordCommon'" in source
    assert "COMMON_PASSWORD_BLOCKLIST" not in source


def test_portal_installation_boundary_precedes_auth_and_getting_started_uses_evidence() -> None:
    shell_source = Path("apps/admin-portal/components/layout/AppShell.tsx").read_text(encoding="utf-8")
    home_source = Path("apps/admin-portal/components/dashboard/PlatformHome.tsx").read_text(encoding="utf-8")

    assert shell_source.index("<InstallationBoundary") < shell_source.index("<AuthProvider>")
    assert "steps.organization_configured" in home_source
    assert "steps.administrator_configured" in home_source


def test_service_contains_database_concurrency_and_cli_reuse_contracts() -> None:
    service_source = Path("apps/api/app/services/installation_setup.py").read_text(encoding="utf-8")
    cli_adapter_source = Path("apps/api/app/identity/installation_bootstrap.py").read_text(encoding="utf-8")

    assert "pg_advisory_xact_lock" in service_source
    assert "InstallationCompletionEvidence(" in service_source
    assert "InstallationSetupService(" in cli_adapter_source
    assert InstallationState.READY_TO_COMPLETE.value == "READY_TO_COMPLETE"


def test_completion_requires_persisted_platform_owner_authority() -> None:
    service_source = Path("apps/api/app/services/installation_setup.py").read_text(encoding="utf-8")

    assert "platform_role.code == PLATFORM_OWNER_ROLE_CODE" in service_source
    assert 'platform_role.config.get("scope") == "platform"' in service_source
    assert 'platform_assignment.principal_type == "user"' in service_source
    assert 'platform_assignment.scope_type == "platform"' in service_source
    assert 'platform_assignment.scope_id == "platform"' in service_source
    assert "required_platform_permissions.issubset(platform_permissions)" in service_source


def _completed_legacy_service():
    setup_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    organization_role_id = uuid.uuid4()
    setup = SimpleNamespace(installation_setup_id=setup_id, setup_schema_version=1)
    completion = SimpleNamespace(
        initial_identity_user_id=user_id,
        initial_role_id=organization_role_id,
        organization_id=organization_id,
        evidence_digest="legacy-digest",
    )
    user = SimpleNamespace(
        id=user_id,
        status="active",
        email_normalized="admin@example.invalid",
        display_name="Administrator",
    )
    organization = SimpleNamespace(id=organization_id, status="active")
    organization_role = SimpleNamespace(
        id=organization_role_id,
        organization_id=organization_id,
        status="active",
        code="example-administrator",
    )
    administrator_evidence = SimpleNamespace(
        evidence_type="administrator_configured",
        evidence_version=1,
        organization_id=organization_id,
        resource_type="identity_user",
        resource_id=str(user_id),
        evidence_payload={
            "email": user.email_normalized,
            "display_name": user.display_name,
            "role_id": str(organization_role_id),
            "role_code": organization_role.code,
        },
        evidence_hash="legacy-administrator-hash",
    )
    evidence = {
        "organization_configured": SimpleNamespace(evidence_hash="organization-hash"),
        "administrator_configured": administrator_evidence,
        "preferences_configured": SimpleNamespace(evidence_hash="preferences-hash"),
    }
    platform_db = MagicMock()
    platform_db.get.side_effect = lambda _model, record_id: (
        organization_role
        if record_id == organization_role_id
        else organization
        if record_id == organization_id
        else None
    )
    platform_db.scalar.return_value = SimpleNamespace()
    identity_db = MagicMock()
    identity_db.get.return_value = user
    identity_db.scalar.return_value = SimpleNamespace()
    service = InstallationSetupService(platform_db, identity_db, Settings())
    service._lock = lambda: None  # type: ignore[method-assign]
    service._current_setup = lambda: setup  # type: ignore[method-assign]
    service._completion = lambda _setup: completion  # type: ignore[method-assign]
    service._evidence = lambda _setup: evidence  # type: ignore[method-assign]
    service._audit = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    def write_evidence(_setup, **values):
        administrator_evidence.evidence_payload = values["payload"]
        administrator_evidence.evidence_hash = "reconciled-administrator-hash"
        return administrator_evidence

    service._write_evidence = write_evidence  # type: ignore[method-assign]
    return service, completion, administrator_evidence, user_id


def test_completed_legacy_installation_reconciles_platform_owner_and_remains_completed(
    monkeypatch,
) -> None:
    service, completion, administrator_evidence, user_id = _completed_legacy_service()
    platform_role = SimpleNamespace(id=uuid.uuid4(), code="platform-owner")
    platform_assignment = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(
        "app.services.installation_setup.reconcile_platform_owner_role",
        lambda *_args, **_kwargs: platform_role,
    )
    monkeypatch.setattr(
        "app.services.installation_setup.reconcile_platform_owner_assignment",
        lambda *_args, **_kwargs: platform_assignment,
    )

    first = service.reconcile_completed_platform_owner()
    second = service.reconcile_completed_platform_owner()

    assert first == second
    assert first["state"] == "COMPLETED"
    assert first["user_id"] == str(user_id)
    assert administrator_evidence.evidence_version == 1
    assert administrator_evidence.resource_id == str(user_id)
    assert administrator_evidence.evidence_payload["platform_role_id"] == str(platform_role.id)
    assert administrator_evidence.evidence_payload["platform_role_code"] == "platform-owner"
    assert administrator_evidence.evidence_payload["platform_assignment_id"] == str(platform_assignment.id)
    assert completion.evidence_digest != "legacy-digest"
    assert service.platform_db.commit.call_count == 2


def test_completed_reconciliation_fails_closed_on_inconsistent_identity_evidence(monkeypatch) -> None:
    service, completion, _administrator_evidence, _user_id = _completed_legacy_service()
    completion.initial_identity_user_id = uuid.uuid4()
    reconcile_role = MagicMock()
    monkeypatch.setattr(
        "app.services.installation_setup.reconcile_platform_owner_role",
        reconcile_role,
    )

    with pytest.raises(InstallationSetupError) as captured:
        service.reconcile_completed_platform_owner()

    assert captured.value.code == "INSTALLATION_EVIDENCE_INCONSISTENT"
    reconcile_role.assert_not_called()
