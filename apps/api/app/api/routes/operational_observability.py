from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.repositories.operational_observability import OperationalObservabilityRepository
from app.schemas.operational_observability import (
    BoundedRetryCreate,
    BoundedRetryRead,
    FailureRecoveryActionCreate,
    FailureRecoveryActionRead,
    IncidentTransitionRequest,
    OperationalDiagnostic,
    OperationalEvidenceRead,
    OperationalExecutionCreate,
    OperationalExecutionRead,
    OperationalIncidentCreate,
    OperationalIncidentRead,
    OperationalReadinessResponse,
    OperationalWorkspaceRuntimeResponse,
    RuntimeComponentCreate,
    RuntimeComponentRead,
    RuntimeObservationCreate,
    RuntimeObservationRead,
    RuntimeResultRequest,
)
from app.services.correlation_context import normalize_correlation_id
from app.services.correlation_trace import build_correlation_trace
from app.services.operational_observability_runtime import (
    build_lease_inventory,
    build_operational_diagnostics,
    build_operational_readiness,
    build_operational_workspace_runtime,
    build_scheduler_inventory,
    build_worker_inventory,
    complete_operational_execution,
    complete_recovery_action,
    complete_retry_attempt,
    create_operational_execution,
    create_recovery_action,
    fail_operational_execution,
    fail_retry_attempt,
    latest_operational_evidence,
    register_component,
    register_incident,
    register_observation,
    register_retry_attempt,
    transition_incident,
)

router = APIRouter(prefix="/platform/operations", tags=["operational-observability"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.operations", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"platform.operations {action} permission is required",
        )


def _scope(
    context: RuntimeRequestContext,
    scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID | None]:
    resolved_scope = scope or context.scope_type
    if resolved_scope == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="platform authorization scope is required"
            )
        return "platform", None
    resolved_org = organization_id or context.organization_id
    if resolved_org is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="operational resource not found")
    return "organization", resolved_org


@router.get("/correlations/{correlation_id}")
def read_correlation_trace(
    correlation_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    try:
        normalized = normalize_correlation_id(correlation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="correlation trace not found") from exc
    scope, organization_id = _scope(context)
    result = build_correlation_trace(
        db,
        normalized,
        scope=scope,
        organization_id=organization_id,
    )
    if not result["found"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="correlation trace not found")
    return result


@router.post("/components", response_model=RuntimeComponentRead)
def create_component(
    payload: RuntimeComponentCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeComponentRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    component = register_component(db, payload.model_copy(update={"scope": scope, "organization_id": organization_id}))
    db.commit()
    return component


@router.get("/components", response_model=list[RuntimeComponentRead])
def list_components(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[RuntimeComponentRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        RuntimeComponentRead.model_validate(item)
        for item in OperationalObservabilityRepository(db).list_components(resolved_scope, resolved_org)
    ]


@router.get("/components/{component_id}", response_model=RuntimeComponentRead)
def get_component(
    component_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeComponentRead:
    _require(context, "read")
    scope, organization_id = _scope(context)
    component = OperationalObservabilityRepository(db).get_component(component_id, scope, organization_id)
    if component is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="component not found")
    return RuntimeComponentRead.model_validate(component)


@router.post("/components/{component_id}/observations", response_model=RuntimeObservationRead)
def create_observation(
    component_id: uuid.UUID,
    payload: RuntimeObservationCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RuntimeObservationRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    component = OperationalObservabilityRepository(db).get_component(component_id, scope, organization_id)
    if component is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="component not found")
    observation = register_observation(db, component, payload)
    db.commit()
    return observation


@router.post("/executions", response_model=OperationalExecutionRead)
def create_execution(
    payload: OperationalExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        execution = create_operational_execution(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        if str(exc) == "idempotency_key_conflict":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="idempotency_key_conflict") from exc
        raise
    db.commit()
    return execution


@router.get("/executions", response_model=list[OperationalExecutionRead])
def list_executions(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalExecutionRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        OperationalExecutionRead.model_validate(item)
        for item in OperationalObservabilityRepository(db).list_executions(resolved_scope, resolved_org)
    ]


@router.get("/executions/{execution_id}", response_model=OperationalExecutionRead)
def get_execution(
    execution_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalExecutionRead:
    _require(context, "read")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    return OperationalExecutionRead.model_validate(execution)


@router.post("/executions/{execution_id}/complete", response_model=OperationalExecutionRead)
def complete_execution(
    execution_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    result = complete_operational_execution(db, execution, payload)
    db.commit()
    return result


@router.post("/executions/{execution_id}/fail", response_model=OperationalExecutionRead)
def fail_execution(
    execution_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    result = fail_operational_execution(db, execution, payload)
    db.commit()
    return result


@router.post("/executions/{execution_id}/abandon", response_model=OperationalExecutionRead)
def abandon_execution(
    execution_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    result = fail_operational_execution(db, execution, payload, status="abandoned")
    db.commit()
    return result


@router.get("/executions/{execution_id}/retries", response_model=list[BoundedRetryRead])
def list_retries(
    execution_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[BoundedRetryRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    return [
        BoundedRetryRead.model_validate(item)
        for item in OperationalObservabilityRepository(db).list_retries(execution_id)
    ]


@router.post("/executions/{execution_id}/retries", response_model=BoundedRetryRead)
def create_retry(
    execution_id: uuid.UUID,
    payload: BoundedRetryCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BoundedRetryRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = OperationalObservabilityRepository(db).get_execution(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
    result = register_retry_attempt(db, execution, payload)
    db.commit()
    return result


@router.post("/retries/{retry_id}/complete", response_model=BoundedRetryRead)
def complete_retry(
    retry_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BoundedRetryRead:
    _require(context, "administer")
    repo = OperationalObservabilityRepository(db)
    scope, organization_id = _scope(context)
    retry = repo.get_retry(retry_id)
    if retry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retry not found")
    execution = repo.get_execution(retry.operational_execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retry not found")
    result = complete_retry_attempt(db, retry, payload)
    db.commit()
    return result


@router.post("/retries/{retry_id}/fail", response_model=BoundedRetryRead)
def fail_retry(
    retry_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BoundedRetryRead:
    _require(context, "administer")
    repo = OperationalObservabilityRepository(db)
    scope, organization_id = _scope(context)
    retry = repo.get_retry(retry_id)
    if retry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retry not found")
    execution = repo.get_execution(retry.operational_execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retry not found")
    result = fail_retry_attempt(db, retry, payload)
    db.commit()
    return result


@router.get("/incidents", response_model=list[OperationalIncidentRead])
def list_incidents(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalIncidentRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        OperationalIncidentRead.model_validate(item)
        for item in OperationalObservabilityRepository(db).list_incidents(resolved_scope, resolved_org)
    ]


@router.post("/incidents", response_model=OperationalIncidentRead)
def create_incident(
    payload: OperationalIncidentCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalIncidentRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    result = register_incident(db, payload.model_copy(update={"scope": scope, "organization_id": organization_id}))
    db.commit()
    return result


@router.get("/incidents/{incident_id}", response_model=OperationalIncidentRead)
def get_incident(
    incident_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalIncidentRead:
    _require(context, "read")
    scope, organization_id = _scope(context)
    incident = OperationalObservabilityRepository(db).get_incident(incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return OperationalIncidentRead.model_validate(incident)


def _transition_incident(
    incident_id: uuid.UUID,
    action: str,
    payload: IncidentTransitionRequest,
    context: RuntimeRequestContext,
    db: Session,
) -> OperationalIncidentRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    incident = OperationalObservabilityRepository(db).get_incident(incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    try:
        result = transition_incident(db, incident, action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/incidents/{incident_id}/acknowledge", response_model=OperationalIncidentRead)
def acknowledge_incident(
    incident_id: uuid.UUID,
    payload: IncidentTransitionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalIncidentRead:
    return _transition_incident(incident_id, "acknowledge", payload, context, db)


@router.post("/incidents/{incident_id}/resolve", response_model=OperationalIncidentRead)
def resolve_incident(
    incident_id: uuid.UUID,
    payload: IncidentTransitionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalIncidentRead:
    return _transition_incident(incident_id, "resolve", payload, context, db)


@router.post("/incidents/{incident_id}/suppress", response_model=OperationalIncidentRead)
def suppress_incident(
    incident_id: uuid.UUID,
    payload: IncidentTransitionRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalIncidentRead:
    return _transition_incident(incident_id, "suppress", payload, context, db)


@router.post("/incidents/{incident_id}/recovery-actions", response_model=FailureRecoveryActionRead)
def create_incident_recovery_action(
    incident_id: uuid.UUID,
    payload: FailureRecoveryActionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> FailureRecoveryActionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    incident = OperationalObservabilityRepository(db).get_incident(incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    result = create_recovery_action(db, incident, payload)
    db.commit()
    return result


@router.get("/incidents/{incident_id}/recovery-actions", response_model=list[FailureRecoveryActionRead])
def list_incident_recovery_actions(
    incident_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[FailureRecoveryActionRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    incident = OperationalObservabilityRepository(db).get_incident(incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return [
        FailureRecoveryActionRead.model_validate(item)
        for item in OperationalObservabilityRepository(db).list_recovery_actions(incident_id)
    ]


@router.post("/recovery-actions/{action_id}/complete", response_model=FailureRecoveryActionRead)
def complete_incident_recovery_action(
    action_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> FailureRecoveryActionRead:
    _require(context, "administer")
    repo = OperationalObservabilityRepository(db)
    scope, organization_id = _scope(context)
    action = repo.get_recovery_action(action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery action not found")
    incident = repo.get_incident(action.incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery action not found")
    result = complete_recovery_action(db, action, payload)
    db.commit()
    return result


@router.post("/recovery-actions/{action_id}/fail", response_model=FailureRecoveryActionRead)
def fail_incident_recovery_action(
    action_id: uuid.UUID,
    payload: RuntimeResultRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> FailureRecoveryActionRead:
    _require(context, "administer")
    repo = OperationalObservabilityRepository(db)
    scope, organization_id = _scope(context)
    action = repo.get_recovery_action(action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery action not found")
    incident = repo.get_incident(action.incident_id, scope, organization_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recovery action not found")
    result = complete_recovery_action(db, action, payload, failed=True)
    db.commit()
    return result


@router.get("/readiness", response_model=OperationalReadinessResponse)
def get_operational_readiness(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalReadinessResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_operational_readiness(db, resolved_scope, resolved_org)


@router.get("/diagnostics", response_model=list[OperationalDiagnostic])
def get_operational_diagnostics(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalDiagnostic]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_operational_diagnostics(db, resolved_scope, resolved_org)


@router.get("/evidence/latest", response_model=list[OperationalEvidenceRead])
def get_latest_operational_evidence(
    scope: str = Query(default="platform"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[OperationalEvidenceRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return latest_operational_evidence(db, resolved_scope, resolved_org)


@router.get("/workers")
def get_operational_workers(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[dict]:
    _require(context, "read")
    return build_worker_inventory(db)


@router.get("/schedulers")
def get_operational_schedulers(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> dict:
    _require(context, "read")
    return build_scheduler_inventory(db)


@router.get("/leases")
def get_operational_leases(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> dict:
    _require(context, "read")
    return build_lease_inventory(db)


@router.get("/observability/runtime", response_model=OperationalWorkspaceRuntimeResponse)
def get_operational_workspace_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalWorkspaceRuntimeResponse:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return build_operational_workspace_runtime(db, scope, organization_id)
