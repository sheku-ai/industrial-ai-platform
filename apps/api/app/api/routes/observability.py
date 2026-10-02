from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.observability import ObservabilityRepository
from app.schemas.observability import (
    AvailabilityWindowCreate,
    AvailabilityWindowRead,
    HealthAcceptanceRead,
    HealthDomainCreate,
    HealthDomainRead,
    HealthEvaluationRead,
    HealthEvaluationRequest,
    HealthEvidenceRead,
    HealthFindingRead,
    HealthHistoryRead,
    HeartbeatCreate,
    HeartbeatRead,
    ObservabilityLatestResponse,
    ObservabilityProfileCreate,
    ObservabilityProfileRead,
    ObservabilityReadinessResponse,
    ObservedComponentCreate,
    ObservedComponentRead,
    ObservedDependencyCreate,
    ObservedDependencyRead,
    ObservedSignalCreate,
    ObservedSignalRead,
)
from app.services.observability_runtime import (
    build_observability_readiness,
    create_observability_profile,
    evaluate_observability,
    latest_observability_result,
    observability_history,
    register_availability_window,
    register_health_domain,
    register_heartbeat,
    register_observed_component,
    register_observed_dependency,
    register_observed_signal,
)

router = APIRouter(prefix="/platform/observability", tags=["platform-observability"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.observability", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"observability {action} permission is required"
        )


def _scope(
    context: RuntimeRequestContext,
    requested_scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[str, uuid.UUID | None]:
    scope = requested_scope or context.scope_type
    if scope == "platform":
        if not context.is_scope("platform"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="platform authorization scope is required"
            )
        return "platform", None
    resolved = organization_id or context.organization_id
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observability resource not found")
    return "organization", resolved


def _error(exc: ValueError) -> HTTPException:
    return runtime_http_error(exc)


@router.post("/profiles", response_model=ObservabilityProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: ObservabilityProfileCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ObservabilityProfileRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = create_observability_profile(
            db,
            payload.model_copy(
                update={"scope": scope, "organization_id": organization_id, "created_by": context.actor_reference}
            ),
        )
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/profiles", response_model=list[ObservabilityProfileRead])
def list_profiles(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[ObservabilityProfileRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        ObservabilityProfileRead.model_validate(item)
        for item in ObservabilityRepository(db).list_profiles(resolved_scope, resolved_org)
    ]


@router.post("/domains", response_model=HealthDomainRead, status_code=status.HTTP_201_CREATED)
def create_domain(
    payload: HealthDomainCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> HealthDomainRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_health_domain(
            db,
            payload.model_copy(
                update={"scope": scope, "organization_id": organization_id, "created_by": context.actor_reference}
            ),
        )
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/domains", response_model=list[HealthDomainRead])
def list_domains(
    profile_id: uuid.UUID, context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> list[HealthDomainRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    profile = ObservabilityRepository(db).get_profile(profile_id, scope, organization_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="observability_profile_not_found")
    return [HealthDomainRead.model_validate(item) for item in ObservabilityRepository(db).list_domains(profile.id)]


@router.post("/components", response_model=ObservedComponentRead, status_code=status.HTTP_201_CREATED)
def create_component(
    payload: ObservedComponentCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ObservedComponentRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_observed_component(
            db,
            payload.model_copy(
                update={"scope": scope, "organization_id": organization_id, "created_by": context.actor_reference}
            ),
        )
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/components", response_model=list[ObservedComponentRead])
def list_components(
    context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> list[ObservedComponentRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return [
        ObservedComponentRead.model_validate(item)
        for item in ObservabilityRepository(db).list_components(scope, organization_id)
    ]


@router.post("/dependencies", response_model=ObservedDependencyRead, status_code=status.HTTP_201_CREATED)
def create_dependency(
    payload: ObservedDependencyCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ObservedDependencyRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    try:
        result = register_observed_dependency(db, scope, organization_id, payload, context.actor_reference)
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/dependencies", response_model=list[ObservedDependencyRead])
def list_dependencies(
    context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> list[ObservedDependencyRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    components = repo.list_components(scope, organization_id)
    return [
        ObservedDependencyRead.model_validate(item) for item in repo.list_dependencies([row.id for row in components])
    ]


@router.post("/signals", response_model=ObservedSignalRead, status_code=status.HTTP_201_CREATED)
def create_signal(
    payload: ObservedSignalCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ObservedSignalRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    try:
        result = register_observed_signal(db, scope, organization_id, payload, context.actor_reference)
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/signals", response_model=list[ObservedSignalRead])
def list_signals(
    limit: int = Query(default=200, ge=1, le=1000),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[ObservedSignalRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    components = repo.list_components(scope, organization_id)
    return [
        ObservedSignalRead.model_validate(item) for item in repo.list_signals([row.id for row in components], limit)
    ]


@router.post("/heartbeats", response_model=HeartbeatRead, status_code=status.HTTP_201_CREATED)
def create_heartbeat(
    payload: HeartbeatCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> HeartbeatRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    try:
        result = register_heartbeat(db, scope, organization_id, payload, context.actor_reference)
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/heartbeats", response_model=list[HeartbeatRead])
def list_heartbeats(
    limit: int = Query(default=200, ge=1, le=1000),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[HeartbeatRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    components = repo.list_components(scope, organization_id)
    return [HeartbeatRead.model_validate(item) for item in repo.list_heartbeats([row.id for row in components], limit)]


@router.post("/availability", response_model=AvailabilityWindowRead, status_code=status.HTTP_201_CREATED)
def create_availability(
    payload: AvailabilityWindowCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> AvailabilityWindowRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    try:
        result = register_availability_window(db, scope, organization_id, payload, context.actor_reference)
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/availability", response_model=list[AvailabilityWindowRead])
def list_availability(
    limit: int = Query(default=200, ge=1, le=1000),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[AvailabilityWindowRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    components = repo.list_components(scope, organization_id)
    return [
        AvailabilityWindowRead.model_validate(item)
        for item in repo.list_availability([row.id for row in components], limit)
    ]


@router.post("/evaluations", response_model=HealthEvaluationRead, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    payload: HealthEvaluationRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> HealthEvaluationRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = evaluate_observability(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "requested_by": context.actor_reference,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        raise _error(exc) from exc
    db.commit()
    return result


def _evaluation(
    repo: ObservabilityRepository, evaluation_id: uuid.UUID | None, scope: str, organization_id: uuid.UUID | None
):
    row = (
        repo.get_evaluation(evaluation_id, scope, organization_id)
        if evaluation_id
        else repo.latest_evaluation(scope, organization_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="observability_evaluation_not_found")
    return row


@router.get("/evaluations", response_model=HealthEvaluationRead)
def read_evaluation(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> HealthEvaluationRead:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return HealthEvaluationRead.model_validate(
        _evaluation(ObservabilityRepository(db), evaluation_id, scope, organization_id)
    )


@router.get("/evidence", response_model=list[HealthEvidenceRead])
def read_evidence(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[HealthEvidenceRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    row = _evaluation(repo, evaluation_id, scope, organization_id)
    return [HealthEvidenceRead.model_validate(item) for item in repo.evidence(row.id)]


@router.get("/acceptance", response_model=HealthAcceptanceRead)
def read_acceptance(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> HealthAcceptanceRead:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    row = _evaluation(repo, evaluation_id, scope, organization_id)
    acceptance = repo.acceptance(row.id)
    if acceptance is None:
        raise HTTPException(status_code=404, detail="observability_acceptance_not_found")
    return HealthAcceptanceRead.model_validate(acceptance)


@router.get("/findings", response_model=list[HealthFindingRead])
def read_findings(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[HealthFindingRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = ObservabilityRepository(db)
    row = _evaluation(repo, evaluation_id, scope, organization_id)
    return [HealthFindingRead.model_validate(item) for item in repo.findings(row.id)]


@router.get("/history", response_model=list[HealthHistoryRead])
def read_history(
    limit: int = Query(default=200, ge=1, le=1000),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[HealthHistoryRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return observability_history(db, scope=scope, organization_id=organization_id, limit=limit)


@router.get("/readiness", response_model=ObservabilityReadinessResponse)
def read_readiness(
    context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> ObservabilityReadinessResponse:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return build_observability_readiness(db, scope=scope, organization_id=organization_id)


@router.get("/latest", response_model=ObservabilityLatestResponse)
def read_latest(
    context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> ObservabilityLatestResponse:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return latest_observability_result(db, scope=scope, organization_id=organization_id)
