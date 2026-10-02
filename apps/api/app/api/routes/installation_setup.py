from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.db import get_identity_db
from app.schemas.installation_setup import (
    InstallationAdministratorRequest,
    InstallationOrganizationRequest,
    InstallationPreferencesRequest,
    InstallationStatusResponse,
)
from app.services.installation_setup import (
    AdministratorSetupCommand,
    InstallationSetupError,
    InstallationSetupService,
    OrganizationSetupCommand,
    PreferencesSetupCommand,
)

router = APIRouter(prefix="/setup", tags=["installation-setup"])


def _authorized(token: str | None, settings: Settings) -> bool:
    configured = settings.sheku_setup_token
    return bool(configured and token and hmac.compare_digest(configured, token))


def _require_setup_token(
    x_sheku_setup_token: str | None = Header(default=None, alias="X-SHEKU-Setup-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not _authorized(x_sheku_setup_token, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSTALLATION_SETUP_NOT_AUTHORIZED",
                "message": "A valid installation setup token is required.",
            },
        )


def _service(platform_db: Session, identity_db: Session, settings: Settings) -> InstallationSetupService:
    return InstallationSetupService(platform_db, identity_db, settings, actor="installation-setup-api")


def _authorized_response(payload: dict) -> dict:
    return {**payload, "token_authorized": True}


def _translate_error(exc: InstallationSetupError) -> HTTPException:
    status_code = status.HTTP_409_CONFLICT
    if exc.code.endswith("_INVALID"):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = {"code": exc.code, "message": str(exc)}
    if exc.reason:
        detail["reason"] = exc.reason
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/status", response_model=InstallationStatusResponse)
def installation_status(
    x_sheku_setup_token: str | None = Header(default=None, alias="X-SHEKU-Setup-Token"),
    platform_db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    service = _service(platform_db, identity_db, settings)
    service.reconcile_legacy_bootstrap()
    authorized = _authorized(x_sheku_setup_token, settings)
    return {
        **service.status(include_details=authorized),
        "token_authorized": authorized,
    }


@router.put(
    "/organization",
    response_model=InstallationStatusResponse,
    dependencies=[Depends(_require_setup_token)],
)
def configure_installation_organization(
    request: InstallationOrganizationRequest,
    platform_db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return _authorized_response(
            _service(platform_db, identity_db, settings).configure_organization(
                OrganizationSetupCommand(name=request.name, slug=request.slug)
            )
        )
    except InstallationSetupError as exc:
        raise _translate_error(exc) from exc


@router.put(
    "/administrator",
    response_model=InstallationStatusResponse,
    dependencies=[Depends(_require_setup_token)],
)
def configure_installation_administrator(
    request: InstallationAdministratorRequest,
    platform_db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return _authorized_response(
            _service(platform_db, identity_db, settings).configure_administrator(
                AdministratorSetupCommand(
                    email=request.email,
                    display_name=request.display_name,
                    password=request.password,
                )
            )
        )
    except InstallationSetupError as exc:
        raise _translate_error(exc) from exc


@router.put(
    "/preferences",
    response_model=InstallationStatusResponse,
    dependencies=[Depends(_require_setup_token)],
)
def configure_installation_preferences(
    request: InstallationPreferencesRequest,
    platform_db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return _authorized_response(
            _service(platform_db, identity_db, settings).configure_preferences(
                PreferencesSetupCommand(language=request.language, timezone=request.timezone)
            )
        )
    except InstallationSetupError as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/complete",
    response_model=InstallationStatusResponse,
    dependencies=[Depends(_require_setup_token)],
)
def complete_installation(
    platform_db: Session = Depends(get_db),
    identity_db: Session = Depends(get_identity_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return _authorized_response(_service(platform_db, identity_db, settings).complete())
    except InstallationSetupError as exc:
        raise _translate_error(exc) from exc
