from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.release_governance import GovernedRelease, ReleaseBuild, ReleaseBuildManifest
from app.repositories.release_governance import ReleaseGovernanceRepository
from app.schemas.baseline_release_evidence import (
    BaselineReleaseEvidenceContract,
    BaselineReleaseEvidenceCreate,
    BaselineReleaseEvidenceRead,
)
from app.schemas.release_governance import (
    BuildManifestCreate,
    BuildManifestRead,
    GovernedReleaseCreate,
    GovernedReleaseRead,
    MigrationRequirementRead,
    ReleaseBuildComplete,
    ReleaseBuildCreate,
    ReleaseBuildRead,
)
from app.services.release_governance_runtime import (
    complete_build,
    create_build,
    create_release,
    governed_release_idempotency_key,
    governed_release_logical_identity,
    register_build_manifest,
    register_migration_requirement,
    stable_hash,
)

BASELINE_CONTRACT_VERSION = "baseline_release_evidence.v1"


def _release_payload(payload: BaselineReleaseEvidenceCreate) -> GovernedReleaseCreate:
    return GovernedReleaseCreate(
        release_code="derived-by-release-governance",
        version=payload.application_version,
        edition=payload.edition,
        channel="stable",
        source_repository=payload.source_repository,
        source_revision=payload.source_revision,
        source_branch=payload.source_branch,
        idempotency_key="derived-by-release-governance",
        created_by=payload.created_by,
    )


def _identity(payload: BaselineReleaseEvidenceCreate) -> str:
    return governed_release_idempotency_key(_release_payload(payload))


def _input_hash(payload: BaselineReleaseEvidenceCreate) -> str:
    return stable_hash(payload.model_dump(mode="json", exclude={"created_by", "execution_key"}))


def _resolve_release(
    db: Session,
    payload: BaselineReleaseEvidenceCreate,
    identity: str,
) -> tuple[GovernedRelease, bool]:
    repository = ReleaseGovernanceRepository(db)
    release_payload = _release_payload(payload)
    existing = repository.get_release_by_idempotency(identity)
    logical_matches = repository.list_releases_by_logical_identity(
        **governed_release_logical_identity(release_payload)
    )
    release = create_release(db, release_payload)
    return release, existing is not None or bool(logical_matches)


def _resolve_build(
    db: Session,
    release: GovernedRelease,
    payload: BaselineReleaseEvidenceCreate,
    identity: str,
    input_hash: str,
) -> tuple[ReleaseBuild, ReleaseBuildManifest, bool]:
    repository = ReleaseGovernanceRepository(db)
    build_key = f"{identity}:build"
    existing = repository.get_build_by_idempotency(release.id, build_key)
    reused = existing is not None
    provenance = {
        "contract_version": BASELINE_CONTRACT_VERSION,
        "baseline_input_hash": input_hash,
        "execution_key": identity,
        "provenance": payload.provenance,
        "lineage": payload.lineage.model_dump(mode="json"),
    }
    build = create_build(
        db,
        release.id,
        ReleaseBuildCreate(
            build_number=f"baseline-{payload.application_version}-{input_hash[:12]}",
            build_timestamp=payload.manifest.build_timestamp,
            builder_type="manual_evidence",
            builder_reference=identity,
            source_revision=payload.source_revision,
            target_platform="other",
            target_architecture="other",
            build_profile="historical_baseline",
            reproducibility_evidence=provenance,
            idempotency_key=build_key,
        ),
    )
    manifest_payload = {
        **payload.manifest.manifest_payload,
        "baseline_release_evidence": provenance,
    }
    manifest = register_build_manifest(
        db,
        build.id,
        BuildManifestCreate(
            **payload.manifest.model_dump(exclude={"manifest_payload"}),
            manifest_payload=manifest_payload,
        ),
    )
    build = complete_build(
        db,
        build.id,
        ReleaseBuildComplete(
            reproducibility_evidence=provenance,
            result_evidence={
                "baseline_manifest_hash": manifest.manifest_hash,
                "evidence_origin": "persisted_historical_release_evidence",
            },
        ),
    )
    return build, manifest, reused


def register_baseline_release_evidence(
    db: Session,
    payload: BaselineReleaseEvidenceCreate,
) -> BaselineReleaseEvidenceRead:
    identity = _identity(payload)
    input_hash = _input_hash(payload)
    release, release_reused = _resolve_release(db, payload, identity)
    target = ReleaseGovernanceRepository(db).get_release(payload.lineage.target_release_id)
    if target is None:
        raise LookupError("baseline_target_release_not_found")
    if (
        target.edition != payload.edition
        or target.id == release.id
        or target.version == payload.application_version
        or payload.lineage.migration.to_revision == payload.alembic_revision
    ):
        raise ValueError("baseline_release_lineage_conflict")
    target_build = ReleaseGovernanceRepository(db).latest_build(target.id)
    target_manifest = (
        ReleaseGovernanceRepository(db).get_build_manifest(target_build.id)
        if target_build is not None
        else None
    )
    if (
        target_manifest is not None
        and target_manifest.database_schema_revision != payload.lineage.migration.to_revision
    ):
        raise ValueError("baseline_release_lineage_conflict")
    build, manifest, build_reused = _resolve_build(db, release, payload, identity, input_hash)
    migration_reused = any(
        item.from_revision == payload.lineage.migration.from_revision
        and item.to_revision == payload.lineage.migration.to_revision
        for item in ReleaseGovernanceRepository(db).list_migration_requirements(target.id)
    )
    migration = register_migration_requirement(db, target.id, payload.lineage.migration)
    evidence = BaselineReleaseEvidenceContract(
        execution_key=identity,
        input_hash=input_hash,
        application_version=payload.application_version,
        alembic_revision=payload.alembic_revision,
        edition=payload.edition,
        release_id=release.id,
        build_id=build.id,
        manifest_id=manifest.id,
        target_release_id=target.id,
        migration_requirement_id=migration.id,
        provenance=payload.provenance,
        lineage=payload.lineage,
        created_at=release.created_at,
    )
    return BaselineReleaseEvidenceRead(
        baseline_release_evidence=evidence,
        backup_evidence_available=False,
        recovery_ready=False,
        upgrade_governance_ready=True,
        application_version=payload.application_version,
        alembic_revision=payload.alembic_revision,
        edition=payload.edition,
        execution_key=identity,
        reused=release_reused and build_reused and migration_reused,
        release=GovernedReleaseRead.model_validate(release),
        build=ReleaseBuildRead.model_validate(build),
        manifest=BuildManifestRead.model_validate(manifest),
        migration_requirement=MigrationRequirementRead.model_validate(migration),
        created_at=release.created_at,
    )
