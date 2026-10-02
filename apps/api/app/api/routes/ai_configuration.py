from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.ai_configuration import (
    AIConfigurationWorkspaceRead,
    DefaultStateRequest,
    EnabledStateRequest,
    ModelConfigurationCreate,
    ModelConfigurationRead,
    ModelConfigurationUpdate,
    ProviderAdapterRead,
    ProviderConfigurationCreate,
    ProviderConfigurationRead,
    ProviderConfigurationUpdate,
    ValidationEvidenceRead,
)
from app.services.ai_configuration import (
    AIConfigurationError,
    AIConfigurationService,
    get_provider_adapter_registry,
    get_secret_resolver_registry,
)

router = APIRouter(prefix="/ai", tags=["ai-configuration"])


def _service(
    context: RuntimeRequestContext,
    db: Session,
) -> AIConfigurationService:
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
    return AIConfigurationService(
        db,
        organization_id=context.organization_id,
        actor_reference=context.actor_reference,
        actor_permissions=context.permissions,
        correlation_id=context.correlation_id,
        adapter_registry=get_provider_adapter_registry(),
        secret_registry=get_secret_resolver_registry(),
    )


def _result(operation):
    try:
        return operation()
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/configuration", response_model=AIConfigurationWorkspaceRead)
def get_ai_configuration_workspace(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).workspace())


@router.get("/provider-adapters", response_model=list[ProviderAdapterRead])
def list_provider_adapters(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).adapters())


@router.get("/providers", response_model=list[ProviderConfigurationRead])
def list_provider_configurations(
    enabled: bool | None = None,
    lifecycle_status: str | None = Query(default=None, pattern="^(active|archived)$"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).list_providers(
            enabled=enabled,
            lifecycle_status=lifecycle_status,
        )
    )


@router.post(
    "/providers",
    response_model=ProviderConfigurationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_configuration(
    payload: ProviderConfigurationCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).create_provider(payload))


@router.get("/providers/{provider_id}", response_model=ProviderConfigurationRead)
def get_provider_configuration(
    provider_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).get_provider(provider_id))


@router.patch("/providers/{provider_id}", response_model=ProviderConfigurationRead)
def update_provider_configuration(
    provider_id: uuid.UUID,
    payload: ProviderConfigurationUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).update_provider(provider_id, payload)
    )


@router.post("/providers/{provider_id}/enabled", response_model=ProviderConfigurationRead)
def set_provider_configuration_enabled(
    provider_id: uuid.UUID,
    payload: EnabledStateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).set_provider_enabled(
            provider_id,
            enabled=payload.enabled,
        )
    )


@router.post("/providers/{provider_id}/archive", response_model=ProviderConfigurationRead)
def archive_provider_configuration(
    provider_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).archive_provider(provider_id))


@router.post("/providers/{provider_id}/restore", response_model=ProviderConfigurationRead)
def restore_provider_configuration(
    provider_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).restore_provider(provider_id))


@router.post(
    "/providers/{provider_id}/validate",
    response_model=ValidationEvidenceRead,
)
def validate_provider_configuration(
    provider_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).validate_provider(provider_id))


@router.get(
    "/providers/{provider_id}/validation/latest",
    response_model=ValidationEvidenceRead,
)
def get_latest_provider_validation(
    provider_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).latest_provider_validation(provider_id)
    )


@router.get("/models", response_model=list[ModelConfigurationRead])
def list_model_configurations(
    provider_id: uuid.UUID | None = None,
    capability: str | None = Query(
        default=None,
        pattern="^(generation|chat|embeddings|reranking|multimodal)$",
    ),
    enabled: bool | None = None,
    lifecycle_status: str | None = Query(default=None, pattern="^(active|archived)$"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).list_models(
            provider_id=provider_id,
            capability=capability,
            enabled=enabled,
            lifecycle_status=lifecycle_status,
        )
    )


@router.post(
    "/models",
    response_model=ModelConfigurationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_model_configuration(
    payload: ModelConfigurationCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).create_model(payload))


@router.get("/models/{model_id}", response_model=ModelConfigurationRead)
def get_model_configuration(
    model_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).get_model(model_id))


@router.patch("/models/{model_id}", response_model=ModelConfigurationRead)
def update_model_configuration(
    model_id: uuid.UUID,
    payload: ModelConfigurationUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).update_model(model_id, payload))


@router.post("/models/{model_id}/enabled", response_model=ModelConfigurationRead)
def set_model_configuration_enabled(
    model_id: uuid.UUID,
    payload: EnabledStateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).set_model_enabled(
            model_id,
            enabled=payload.enabled,
        )
    )


@router.post("/models/{model_id}/archive", response_model=ModelConfigurationRead)
def archive_model_configuration(
    model_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).archive_model(model_id))


@router.post("/models/{model_id}/restore", response_model=ModelConfigurationRead)
def restore_model_configuration(
    model_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).restore_model(model_id))


@router.post("/models/{model_id}/default", response_model=ModelConfigurationRead)
def set_default_model_configuration(
    model_id: uuid.UUID,
    payload: DefaultStateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(
        lambda: _service(context, db).set_default_model(
            model_id,
            is_default=payload.is_default,
        )
    )


@router.post(
    "/models/{model_id}/validate",
    response_model=ValidationEvidenceRead,
)
def validate_model_configuration(
    model_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).validate_model(model_id))


@router.get(
    "/models/{model_id}/validation/latest",
    response_model=ValidationEvidenceRead,
)
def get_latest_model_validation(
    model_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return _result(lambda: _service(context, db).latest_model_validation(model_id))
