from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.installation_setup import (
    _require_setup_token,
    _translate_error,
    complete_installation,
    configure_installation_administrator,
    configure_installation_organization,
    configure_installation_preferences,
    installation_status,
    router,
)
from app.core.config import Settings
from app.schemas.installation_setup import (
    InstallationAdministratorRequest,
    InstallationOrganizationRequest,
    InstallationPreferencesRequest,
)
from app.services.installation_setup import InstallationSetupError


def test_installation_api_exposes_the_complete_setup_contract() -> None:
    methods_by_path = {
        route.path: route.methods
        for route in router.routes
    }

    assert methods_by_path["/setup/status"] == {"GET"}
    assert methods_by_path["/setup/organization"] == {"PUT"}
    assert methods_by_path["/setup/administrator"] == {"PUT"}
    assert methods_by_path["/setup/preferences"] == {"PUT"}
    assert methods_by_path["/setup/complete"] == {"POST"}


def test_installation_mutations_reject_missing_or_incorrect_setup_token() -> None:
    settings = Settings(sheku_setup_token="installation-secret")

    for token in (None, "", "incorrect"):
        with pytest.raises(HTTPException) as captured:
            _require_setup_token(token, settings)
        assert captured.value.status_code == 403
        assert captured.value.detail["code"] == "INSTALLATION_SETUP_NOT_AUTHORIZED"

    assert _require_setup_token("installation-secret", settings) is None


def test_installation_errors_have_stable_http_statuses_and_codes() -> None:
    invalid = _translate_error(InstallationSetupError("INSTALLATION_PREFERENCES_INVALID", "invalid"))
    conflict = _translate_error(InstallationSetupError("INSTALLATION_ALREADY_COMPLETED", "complete"))

    assert invalid.status_code == 422
    assert invalid.detail == {"code": "INSTALLATION_PREFERENCES_INVALID", "message": "invalid"}
    assert conflict.status_code == 409
    assert conflict.detail == {"code": "INSTALLATION_ALREADY_COMPLETED", "message": "complete"}


def test_installation_password_policy_errors_expose_a_stable_reason() -> None:
    invalid = _translate_error(
        InstallationSetupError(
            "INSTALLATION_ADMINISTRATOR_INVALID",
            "The administrator password does not meet the configured password policy.",
            reason="PASSWORD_COMMON",
        )
    )

    assert invalid.status_code == 422
    assert invalid.detail == {
        "code": "INSTALLATION_ADMINISTRATOR_INVALID",
        "message": "The administrator password does not meet the configured password policy.",
        "reason": "PASSWORD_COMMON",
    }


@pytest.mark.parametrize("state", ["UNCONFIGURED", "IN_PROGRESS", "COMPLETED"])
def test_status_endpoint_returns_service_derived_state(monkeypatch, state: str) -> None:
    class StubService:
        def reconcile_legacy_bootstrap(self) -> bool:
            return False

        def status(self, *, include_details: bool) -> dict:
            return {
                "state": state,
                "token_authorized": False,
                "setup_available": state != "COMPLETED",
                "setup_schema_version": 1,
                "steps": {},
                "next_step": None,
                "ready_to_complete": False,
                "details": {"authorized": {}} if include_details else {},
                "password_policy": {
                    "min_length": 15,
                    "max_length": 128,
                    "block_context": True,
                    "block_common": True,
                },
            }

    monkeypatch.setattr(
        "app.api.routes.installation_setup._service",
        lambda *_args: StubService(),
    )
    settings = Settings(sheku_setup_token="installation-secret")

    public = installation_status(None, object(), object(), settings)  # type: ignore[arg-type]
    authorized = installation_status(
        "installation-secret", object(), object(), settings  # type: ignore[arg-type]
    )

    assert public["state"] == state
    assert public["token_authorized"] is False
    assert public["details"] == {}
    assert authorized["token_authorized"] is True
    assert authorized["details"] == {"authorized": {}}


def test_authorized_setup_endpoints_delegate_to_the_application_service(monkeypatch) -> None:
    calls: list[tuple[str, object | None]] = []

    class StubService:
        def configure_organization(self, command) -> dict:
            calls.append(("organization", command))
            return {"state": "IN_PROGRESS"}

        def configure_administrator(self, command) -> dict:
            calls.append(("administrator", command))
            return {"state": "IN_PROGRESS"}

        def configure_preferences(self, command) -> dict:
            calls.append(("preferences", command))
            return {"state": "READY_TO_COMPLETE"}

        def complete(self) -> dict:
            calls.append(("complete", None))
            return {"state": "COMPLETED"}

    monkeypatch.setattr(
        "app.api.routes.installation_setup._service",
        lambda *_args: StubService(),
    )
    dependencies = (object(), object(), Settings())

    organization = configure_installation_organization(
        InstallationOrganizationRequest(name="Example", slug="example"),
        *dependencies,  # type: ignore[arg-type]
    )
    administrator = configure_installation_administrator(
        InstallationAdministratorRequest(
            email="admin@example.invalid",
            display_name="Administrator",
            password="valid-password",
        ),
        *dependencies,  # type: ignore[arg-type]
    )
    preferences = configure_installation_preferences(
        InstallationPreferencesRequest(language="en", timezone="UTC"),
        *dependencies,  # type: ignore[arg-type]
    )
    completion = complete_installation(*dependencies)  # type: ignore[arg-type]

    assert [name for name, _command in calls] == [
        "organization",
        "administrator",
        "preferences",
        "complete",
    ]
    assert organization["token_authorized"] is True
    assert administrator["token_authorized"] is True
    assert preferences["token_authorized"] is True
    assert completion == {"state": "COMPLETED", "token_authorized": True}
