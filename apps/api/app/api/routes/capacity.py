from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.capacity import CapacityRepository
from app.schemas.capacity import (
    CapacityEvaluationRead,
    CapacityEvaluationRequest,
    CapacityEvidenceCreate,
    CapacityEvidenceRead,
    CapacityFindingRead,
    CapacityLatestResponse,
    CapacityProfileCreate,
    CapacityProfileRead,
    CapacityReadinessResponse,
    CapacityRecommendationRead,
    CapacityTrendRead,
    LoadTestExecutionComplete,
    LoadTestExecutionCreate,
    LoadTestExecutionRead,
    LoadTestResultCreate,
    LoadTestResultRead,
)
from app.services.capacity_runtime import (
    build_capacity_readiness,
    capacity_history,
    complete_load_test,
    create_capacity_profile,
    evaluate_capacity,
    latest_capacity_result,
    register_capacity_evidence,
    register_load_test,
    register_load_test_result,
)

router = APIRouter(prefix="/platform/capacity", tags=["platform-capacity"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.capacity", action):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"capacity {action} permission is required")


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
    resolved_org = organization_id or context.organization_id
    if resolved_org is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    if context.organization_id is not None and context.organization_id != resolved_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capacity resource not found")
    return "organization", resolved_org


def _translate_error(exc: ValueError) -> HTTPException:
    return runtime_http_error(exc)


@router.post("/profiles", response_model=CapacityProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: CapacityProfileCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> CapacityProfileRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = create_capacity_profile(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "created_by": payload.created_by or context.actor_reference,
                }
            ),
        )
    except ValueError as exc:
        raise _translate_error(exc) from exc
    db.commit()
    return result


@router.get("/profiles", response_model=list[CapacityProfileRead])
def list_profiles(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[CapacityProfileRead]:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return [
        CapacityProfileRead.model_validate(item)
        for item in CapacityRepository(db).list_profiles(resolved_scope, resolved_org)
    ]


@router.post("/load-tests", response_model=LoadTestExecutionRead, status_code=status.HTTP_201_CREATED)
def create_load_test(
    payload: LoadTestExecutionCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> LoadTestExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = register_load_test(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "requested_by": payload.requested_by or context.actor_reference,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        raise _translate_error(exc) from exc
    db.commit()
    return result


@router.post("/load-tests/{execution_id}/results", response_model=LoadTestResultRead)
def create_load_result(
    execution_id: uuid.UUID,
    payload: LoadTestResultCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> LoadTestResultRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = CapacityRepository(db).get_load_test(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="load_test_execution_not_found")
    try:
        result = register_load_test_result(db, execution, payload)
    except ValueError as exc:
        raise _translate_error(exc) from exc
    db.commit()
    return result


@router.post("/load-tests/{execution_id}/complete", response_model=LoadTestExecutionRead)
def finish_load_test(
    execution_id: uuid.UUID,
    payload: LoadTestExecutionComplete,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> LoadTestExecutionRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    execution = CapacityRepository(db).get_load_test(execution_id, scope, organization_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="load_test_execution_not_found")
    try:
        result = complete_load_test(db, execution, payload)
    except ValueError as exc:
        raise _translate_error(exc) from exc
    db.commit()
    return result


@router.post("/evaluations", response_model=CapacityEvaluationRead, status_code=status.HTTP_201_CREATED)
def execute_evaluation(
    payload: CapacityEvaluationRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> CapacityEvaluationRead:
    _require(context, "administer")
    scope, organization_id = _scope(context, payload.scope, payload.organization_id)
    try:
        result = evaluate_capacity(
            db,
            payload.model_copy(
                update={
                    "scope": scope,
                    "organization_id": organization_id,
                    "requested_by": payload.requested_by or context.actor_reference,
                    "correlation_id": context.correlation_id,
                }
            ),
        )
    except ValueError as exc:
        raise _translate_error(exc) from exc
    db.commit()
    return result


@router.post("/evaluations/{evaluation_id}/evidence", response_model=CapacityEvidenceRead)
def create_evidence(
    evaluation_id: uuid.UUID,
    payload: CapacityEvidenceCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> CapacityEvidenceRead:
    _require(context, "administer")
    scope, organization_id = _scope(context)
    evaluation = CapacityRepository(db).get_evaluation(evaluation_id, scope, organization_id)
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capacity_evaluation_not_found")
    result = register_capacity_evidence(db, evaluation, payload)
    db.commit()
    return result


@router.get("/readiness", response_model=CapacityReadinessResponse)
def read_readiness(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    organization_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> CapacityReadinessResponse:
    _require(context, "read")
    resolved_scope, resolved_org = _scope(context, scope, organization_id)
    return build_capacity_readiness(db, scope=resolved_scope, organization_id=resolved_org)


def _evaluation_or_latest(
    repo: CapacityRepository, evaluation_id: uuid.UUID | None, scope: str, organization_id: uuid.UUID | None
):
    evaluation = (
        repo.get_evaluation(evaluation_id, scope, organization_id)
        if evaluation_id
        else repo.latest_evaluation(scope, organization_id)
    )
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capacity_evaluation_not_found")
    return evaluation


@router.get("/findings", response_model=list[CapacityFindingRead])
def read_findings(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[CapacityFindingRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = CapacityRepository(db)
    evaluation = _evaluation_or_latest(repo, evaluation_id, scope, organization_id)
    return [CapacityFindingRead.model_validate(item) for item in repo.findings(evaluation.id)]


@router.get("/recommendations", response_model=list[CapacityRecommendationRead])
def read_recommendations(
    evaluation_id: uuid.UUID | None = Query(default=None),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[CapacityRecommendationRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    repo = CapacityRepository(db)
    evaluation = _evaluation_or_latest(repo, evaluation_id, scope, organization_id)
    return [CapacityRecommendationRead.model_validate(item) for item in repo.recommendations(evaluation.id)]


@router.get("/history", response_model=list[CapacityTrendRead])
def read_history(
    limit: int = Query(default=200, ge=1, le=1000),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[CapacityTrendRead]:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return capacity_history(db, scope=scope, organization_id=organization_id, limit=limit)


@router.get("/latest", response_model=CapacityLatestResponse)
def read_latest(
    context: RuntimeRequestContext = Depends(get_runtime_context), db: Session = Depends(get_db)
) -> CapacityLatestResponse:
    _require(context, "read")
    scope, organization_id = _scope(context)
    return latest_capacity_result(db, scope=scope, organization_id=organization_id)
