import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.connector_configuration import (
    ConnectorConfigurationCreate,
    ConnectorConfigurationRead,
    ConnectorConfigurationUpdate,
    ConnectorEnabledStateRequest,
    ConnectorLifecycleRequest,
)
from app.schemas.connector_workspace import ConnectorWorkspaceRuntimeResponse
from app.services.connector_configuration import (
    ConnectorConfigurationError,
    ConnectorConfigurationService,
    get_connector_secret_registry,
)
from app.services.connector_workspace_runtime import build_connector_workspace_runtime

router = APIRouter(prefix="/connectors/workspace", tags=["connector-workspace"])


def _service(
    context: RuntimeRequestContext,
    db: Session,
) -> ConnectorConfigurationService:
    if context.scope_type != "organization" or context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization_scope_required",
        )
    if not context.actor_reference:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
        )
    return ConnectorConfigurationService(
        db,
        organization_id=context.organization_id,
        actor_reference=context.actor_reference,
        actor_permissions=context.permissions,
        correlation_id=context.correlation_id,
        secret_registry=get_connector_secret_registry(),
    )


def _result(operation):
    try:
        return operation()
    except ConnectorConfigurationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/runtime", response_model=ConnectorWorkspaceRuntimeResponse)
def get_connector_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    service = _service(context, db)
    return build_connector_workspace_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=False,
        capabilities={
            "read": context.has_permission("reference_tenant", "read"),
            "administer": context.has_permission("reference_tenant", "administer"),
        },
        credential_resolver_types=service.resolver_types,
    )


@router.get(
    "/configurations/{connector_id}",
    response_model=ConnectorConfigurationRead,
)
def get_connector_configuration(
    connector_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).get(connector_id))


@router.post(
    "/configurations",
    response_model=ConnectorConfigurationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_connector_configuration(
    payload: ConnectorConfigurationCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).create(payload))


@router.patch(
    "/configurations/{connector_id}",
    response_model=ConnectorConfigurationRead,
)
def update_connector_configuration(
    connector_id: uuid.UUID,
    payload: ConnectorConfigurationUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).update(connector_id, payload))


@router.post(
    "/configurations/{connector_id}/enabled",
    response_model=ConnectorConfigurationRead,
)
def set_connector_configuration_enabled(
    connector_id: uuid.UUID,
    payload: ConnectorEnabledStateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).set_enabled(
            connector_id,
            enabled=payload.enabled,
            expected_version=payload.expected_version,
        )
    )


@router.post(
    "/configurations/{connector_id}/archive",
    response_model=ConnectorConfigurationRead,
)
def archive_connector_configuration(
    connector_id: uuid.UUID,
    payload: ConnectorLifecycleRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).archive(
            connector_id,
            expected_version=payload.expected_version,
        )
    )


@router.post(
    "/configurations/{connector_id}/restore",
    response_model=ConnectorConfigurationRead,
)
def restore_connector_configuration(
    connector_id: uuid.UUID,
    payload: ConnectorLifecycleRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).restore(
            connector_id,
            expected_version=payload.expected_version,
        )
    )
