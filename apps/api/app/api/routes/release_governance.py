from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.readiness_runtime_context import get_readiness_runtime_context as get_runtime_context
from app.api.dependencies.runtime_context import RuntimeRequestContext
from app.api.runtime_errors import runtime_http_error
from app.db.session import get_db
from app.repositories.release_governance import ReleaseGovernanceRepository
from app.repositories.release_operational_evidence import ReleaseOperationalEvidenceRepository
from app.schemas.baseline_release_evidence import BaselineReleaseEvidenceCreate, BaselineReleaseEvidenceRead
from app.schemas.release_governance import (
    BuildManifestCreate,
    BuildManifestRead,
    DeploymentManifestCreate,
    DeploymentManifestRead,
    GovernedReleaseCreate,
    GovernedReleaseRead,
    GovernedReleaseUpdate,
    LatestReleaseReadinessResponse,
    LatestReleaseResponse,
    MigrationRequirementCreate,
    MigrationRequirementRead,
    ReleaseAcceptanceRead,
    ReleaseArtifactCreate,
    ReleaseArtifactRead,
    ReleaseArtifactVerify,
    ReleaseBuildComplete,
    ReleaseBuildCreate,
    ReleaseBuildRead,
    ReleaseCompatibilityCreate,
    ReleaseCompatibilityRead,
    ReleaseReadinessResponse,
    RollbackTargetCreate,
    RollbackTargetRead,
)
from app.schemas.release_operational_evidence import (
    OperationalEvidenceRead,
    OperationalRefreshSummaryRequest,
    ReleaseEligibilityRequest,
)
from app.services.baseline_release_evidence_runtime import register_baseline_release_evidence
from app.services.release_governance_runtime import (
    complete_build,
    create_build,
    create_release,
    evaluate_release_acceptance,
    get_latest_release,
    get_latest_release_readiness,
    get_release_readiness,
    register_artifact,
    register_build_manifest,
    register_compatibility,
    register_deployment_manifest,
    register_migration_requirement,
    register_rollback_target,
    update_release,
    verify_artifact,
)
from app.services.release_operational_evidence_runtime import (
    evaluate_rollback_eligibility,
    evaluate_upgrade_readiness,
    persist_operational_refresh_summary,
)

router = APIRouter(prefix="/platform", tags=["release-governance"])


def _authorize(context: RuntimeRequestContext, action: str) -> None:
    if not context.is_scope("platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="platform authorization scope is required")
    if not context.has_permission("platform.release_governance", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"platform.release_governance {action} permission is required",
        )


def _run(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except (LookupError, ValueError) as exc:
        raise runtime_http_error(exc) from exc


@router.post("/releases", response_model=GovernedReleaseRead, status_code=status.HTTP_201_CREATED)
def create_governed_release(
    payload: GovernedReleaseCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> GovernedReleaseRead:
    _authorize(context, "administer")
    request = payload if payload.created_by else payload.model_copy(update={"created_by": context.actor_reference})
    result = _run(lambda: create_release(db, request))
    db.commit()
    return GovernedReleaseRead.model_validate(result)


@router.post(
    "/releases/baseline-evidence",
    response_model=BaselineReleaseEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_baseline_release_evidence(
    payload: BaselineReleaseEvidenceCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BaselineReleaseEvidenceRead:
    _authorize(context, "administer")
    request = payload.model_copy(
        update={
            "created_by": payload.created_by or context.actor_reference,
        }
    )
    result = _run(lambda: register_baseline_release_evidence(db, request))
    db.commit()
    return result


@router.get("/releases", response_model=list[GovernedReleaseRead])
def list_governed_releases(
    edition: str | None = Query(default=None, pattern="^(community|enterprise)$"),
    release_status: str | None = Query(default=None, alias="status"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[GovernedReleaseRead]:
    _authorize(context, "read")
    return [
        GovernedReleaseRead.model_validate(item)
        for item in ReleaseGovernanceRepository(db).list_releases(edition=edition, status=release_status)
    ]


@router.get("/releases/latest", response_model=LatestReleaseResponse)
def read_latest_release(
    edition: str | None = Query(default=None, pattern="^(community|enterprise)$"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> LatestReleaseResponse:
    _authorize(context, "read")
    return get_latest_release(db, edition=edition)


@router.get("/releases/latest/readiness", response_model=LatestReleaseReadinessResponse)
def read_latest_release_readiness(
    edition: str | None = Query(default=None, pattern="^(community|enterprise)$"),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> LatestReleaseReadinessResponse:
    _authorize(context, "read")
    return get_latest_release_readiness(db, edition=edition)


@router.get("/releases/{release_id}", response_model=GovernedReleaseRead)
def read_governed_release(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> GovernedReleaseRead:
    _authorize(context, "read")
    release = _run(lambda: ReleaseGovernanceRepository(db).get_release(release_id))
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release_not_found")
    return GovernedReleaseRead.model_validate(release)


@router.patch("/releases/{release_id}", response_model=GovernedReleaseRead)
def update_governed_release(
    release_id: uuid.UUID,
    payload: GovernedReleaseUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> GovernedReleaseRead:
    _authorize(context, "administer")
    result = _run(lambda: update_release(db, release_id, payload))
    db.commit()
    return GovernedReleaseRead.model_validate(result)


@router.post("/releases/{release_id}/builds", response_model=ReleaseBuildRead, status_code=status.HTTP_201_CREATED)
def create_release_build(
    release_id: uuid.UUID,
    payload: ReleaseBuildCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseBuildRead:
    _authorize(context, "administer")
    result = _run(lambda: create_build(db, release_id, payload))
    db.commit()
    return ReleaseBuildRead.model_validate(result)


@router.get("/releases/{release_id}/builds", response_model=list[ReleaseBuildRead])
def list_release_builds(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[ReleaseBuildRead]:
    _authorize(context, "read")
    repository = ReleaseGovernanceRepository(db)
    if repository.get_release(release_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release_not_found")
    return [ReleaseBuildRead.model_validate(item) for item in repository.list_builds(release_id)]


@router.post("/builds/{build_id}/complete", response_model=ReleaseBuildRead)
def complete_release_build(
    build_id: uuid.UUID,
    payload: ReleaseBuildComplete,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseBuildRead:
    _authorize(context, "administer")
    result = _run(lambda: complete_build(db, build_id, payload))
    db.commit()
    return ReleaseBuildRead.model_validate(result)


@router.post("/builds/{build_id}/manifest", response_model=BuildManifestRead, status_code=status.HTTP_201_CREATED)
def create_build_manifest(
    build_id: uuid.UUID,
    payload: BuildManifestCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BuildManifestRead:
    _authorize(context, "administer")
    result = _run(lambda: register_build_manifest(db, build_id, payload))
    db.commit()
    return BuildManifestRead.model_validate(result)


@router.get("/builds/{build_id}/manifest", response_model=BuildManifestRead)
def read_build_manifest(
    build_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> BuildManifestRead:
    _authorize(context, "read")
    manifest = ReleaseGovernanceRepository(db).get_build_manifest(build_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build_manifest_not_found")
    return BuildManifestRead.model_validate(manifest)


@router.post(
    "/releases/{release_id}/deployment-manifest",
    response_model=DeploymentManifestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_deployment_manifest(
    release_id: uuid.UUID,
    payload: DeploymentManifestCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> DeploymentManifestRead:
    _authorize(context, "administer")
    result = _run(lambda: register_deployment_manifest(db, release_id, payload))
    db.commit()
    return DeploymentManifestRead.model_validate(result)


@router.get("/releases/{release_id}/deployment-manifest", response_model=DeploymentManifestRead)
def read_deployment_manifest(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> DeploymentManifestRead:
    _authorize(context, "read")
    manifest = ReleaseGovernanceRepository(db).get_deployment_manifest(release_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deployment_manifest_not_found")
    return DeploymentManifestRead.model_validate(manifest)


@router.post(
    "/releases/{release_id}/artifacts", response_model=ReleaseArtifactRead, status_code=status.HTTP_201_CREATED
)
def create_release_artifact(
    release_id: uuid.UUID,
    payload: ReleaseArtifactCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseArtifactRead:
    _authorize(context, "administer")
    result = _run(lambda: register_artifact(db, release_id, payload))
    db.commit()
    return ReleaseArtifactRead.model_validate(result)


@router.get("/releases/{release_id}/artifacts", response_model=list[ReleaseArtifactRead])
def list_release_artifacts(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> list[ReleaseArtifactRead]:
    _authorize(context, "read")
    return [
        ReleaseArtifactRead.model_validate(item) for item in ReleaseGovernanceRepository(db).list_artifacts(release_id)
    ]


@router.post("/artifacts/{artifact_id}/verify", response_model=ReleaseArtifactRead)
def verify_release_artifact(
    artifact_id: uuid.UUID,
    payload: ReleaseArtifactVerify,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseArtifactRead:
    _authorize(context, "administer")
    result = _run(lambda: verify_artifact(db, artifact_id, payload))
    db.commit()
    return ReleaseArtifactRead.model_validate(result)


@router.post(
    "/releases/{release_id}/compatibility", response_model=ReleaseCompatibilityRead, status_code=status.HTTP_201_CREATED
)
def create_release_compatibility(
    release_id: uuid.UUID,
    payload: ReleaseCompatibilityCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseCompatibilityRead:
    _authorize(context, "administer")
    result = _run(lambda: register_compatibility(db, release_id, payload))
    db.commit()
    return ReleaseCompatibilityRead.model_validate(result)


@router.post(
    "/releases/{release_id}/migration-requirements",
    response_model=MigrationRequirementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_release_migration_requirement(
    release_id: uuid.UUID,
    payload: MigrationRequirementCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> MigrationRequirementRead:
    _authorize(context, "administer")
    result = _run(lambda: register_migration_requirement(db, release_id, payload))
    db.commit()
    return MigrationRequirementRead.model_validate(result)


@router.post(
    "/releases/{release_id}/rollback-target", response_model=RollbackTargetRead, status_code=status.HTTP_201_CREATED
)
def create_release_rollback_target(
    release_id: uuid.UUID,
    payload: RollbackTargetCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> RollbackTargetRead:
    _authorize(context, "administer")
    result = _run(lambda: register_rollback_target(db, release_id, payload))
    db.commit()
    return RollbackTargetRead.model_validate(result)


@router.post("/releases/{release_id}/evaluate", response_model=ReleaseAcceptanceRead)
def evaluate_governed_release(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseAcceptanceRead:
    _authorize(context, "administer")
    result = _run(lambda: evaluate_release_acceptance(db, release_id))
    db.commit()
    return ReleaseAcceptanceRead.model_validate(result)


@router.get("/releases/{release_id}/readiness", response_model=ReleaseReadinessResponse)
def read_release_readiness(
    release_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> ReleaseReadinessResponse:
    _authorize(context, "read")
    return _run(lambda: get_release_readiness(db, release_id))


@router.post("/release-operational-evidence/upgrade-readiness", response_model=OperationalEvidenceRead)
def create_upgrade_readiness_evidence(
    payload: ReleaseEligibilityRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _authorize(context, "administer")
    request = payload.model_copy(update={"correlation_id": context.correlation_id})
    result = _run(lambda: evaluate_upgrade_readiness(db, request, payload.manifest))
    db.commit()
    return result


@router.post("/release-operational-evidence/rollback-eligibility", response_model=OperationalEvidenceRead)
def create_rollback_eligibility_evidence(
    payload: ReleaseEligibilityRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _authorize(context, "administer")
    request = payload.model_copy(update={"correlation_id": context.correlation_id})
    result = _run(lambda: evaluate_rollback_eligibility(db, request, payload.manifest))
    db.commit()
    return result


@router.post("/release-operational-evidence/refresh-summary", response_model=OperationalEvidenceRead)
def create_operational_refresh_summary(
    payload: OperationalRefreshSummaryRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _authorize(context, "administer")
    request = payload.model_copy(update={"correlation_id": context.correlation_id})
    result = _run(
        lambda: persist_operational_refresh_summary(
            db,
            request,
            payload.summary,
            payload.source_evidence_ids,
        )
    )
    db.commit()
    return result


@router.get("/release-operational-evidence/{evidence_id}", response_model=OperationalEvidenceRead)
def read_release_operational_evidence(
    evidence_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
) -> OperationalEvidenceRead:
    _authorize(context, "read")
    row = ReleaseOperationalEvidenceRepository(db).get(evidence_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release_operational_evidence_not_found")
    return OperationalEvidenceRead.model_validate(row)
