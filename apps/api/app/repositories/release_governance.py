from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.release_governance import (
    GovernedRelease,
    ReleaseAcceptanceEvidence,
    ReleaseArtifact,
    ReleaseBuild,
    ReleaseBuildManifest,
    ReleaseCompatibility,
    ReleaseDeploymentManifest,
    ReleaseMigrationRequirement,
    ReleaseRollbackTarget,
)


class ReleaseGovernanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_release(self, release_id: uuid.UUID) -> GovernedRelease | None:
        return self.db.get(GovernedRelease, release_id)

    def get_release_by_code(self, release_code: str) -> GovernedRelease | None:
        return self.db.scalar(select(GovernedRelease).where(GovernedRelease.release_code == release_code))

    def get_release_by_idempotency(self, idempotency_key: str) -> GovernedRelease | None:
        return self.db.scalar(select(GovernedRelease).where(GovernedRelease.idempotency_key == idempotency_key))

    def list_releases_by_logical_identity(
        self,
        *,
        version: str,
        edition: str,
        channel: str,
        contract_version: str,
        source_repository: str,
        source_revision: str,
    ) -> list[GovernedRelease]:
        return list(
            self.db.scalars(
                select(GovernedRelease)
                .where(
                    GovernedRelease.version == version,
                    GovernedRelease.edition == edition,
                    GovernedRelease.channel == channel,
                    GovernedRelease.contract_version == contract_version,
                    GovernedRelease.source_repository == source_repository,
                    GovernedRelease.source_revision == source_revision,
                )
                .order_by(GovernedRelease.created_at.desc(), GovernedRelease.id.desc())
            ).all()
        )

    def list_releases(self, *, edition: str | None = None, status: str | None = None) -> list[GovernedRelease]:
        statement = select(GovernedRelease)
        if edition:
            statement = statement.where(GovernedRelease.edition == edition)
        if status:
            statement = statement.where(GovernedRelease.status == status)
        return list(self.db.scalars(statement.order_by(GovernedRelease.created_at.desc())).all())

    def latest_release(self, *, edition: str | None = None) -> GovernedRelease | None:
        statement = select(GovernedRelease)
        if edition:
            statement = statement.where(GovernedRelease.edition == edition)
        return self.db.scalar(statement.order_by(GovernedRelease.created_at.desc()).limit(1))

    def get_build(self, build_id: uuid.UUID) -> ReleaseBuild | None:
        return self.db.get(ReleaseBuild, build_id)

    def list_builds(self, release_id: uuid.UUID) -> list[ReleaseBuild]:
        return list(
            self.db.scalars(
                select(ReleaseBuild)
                .where(ReleaseBuild.release_id == release_id)
                .order_by(ReleaseBuild.created_at.desc())
            ).all()
        )

    def latest_build(self, release_id: uuid.UUID) -> ReleaseBuild | None:
        return self.db.scalar(
            select(ReleaseBuild)
            .where(ReleaseBuild.release_id == release_id)
            .order_by(ReleaseBuild.created_at.desc())
            .limit(1)
        )

    def get_build_by_idempotency(self, release_id: uuid.UUID, idempotency_key: str) -> ReleaseBuild | None:
        return self.db.scalar(
            select(ReleaseBuild).where(
                ReleaseBuild.release_id == release_id,
                ReleaseBuild.idempotency_key == idempotency_key,
            )
        )

    def get_build_manifest(self, build_id: uuid.UUID) -> ReleaseBuildManifest | None:
        return self.db.scalar(select(ReleaseBuildManifest).where(ReleaseBuildManifest.build_id == build_id))

    def get_deployment_manifest(self, release_id: uuid.UUID) -> ReleaseDeploymentManifest | None:
        return self.db.scalar(
            select(ReleaseDeploymentManifest).where(ReleaseDeploymentManifest.release_id == release_id)
        )

    def list_artifacts(self, release_id: uuid.UUID) -> list[ReleaseArtifact]:
        return list(
            self.db.scalars(
                select(ReleaseArtifact)
                .where(ReleaseArtifact.release_id == release_id)
                .order_by(ReleaseArtifact.artifact_code.asc())
            ).all()
        )

    def get_artifact(self, artifact_id: uuid.UUID) -> ReleaseArtifact | None:
        return self.db.get(ReleaseArtifact, artifact_id)

    def get_artifact_by_code(
        self, release_id: uuid.UUID, build_id: uuid.UUID, artifact_code: str
    ) -> ReleaseArtifact | None:
        return self.db.scalar(
            select(ReleaseArtifact).where(
                ReleaseArtifact.release_id == release_id,
                ReleaseArtifact.build_id == build_id,
                ReleaseArtifact.artifact_code == artifact_code,
            )
        )

    def list_compatibility(self, release_id: uuid.UUID) -> list[ReleaseCompatibility]:
        return list(
            self.db.scalars(
                select(ReleaseCompatibility)
                .where(ReleaseCompatibility.release_id == release_id)
                .order_by(ReleaseCompatibility.compatibility_type.asc())
            ).all()
        )

    def list_migration_requirements(self, release_id: uuid.UUID) -> list[ReleaseMigrationRequirement]:
        return list(
            self.db.scalars(
                select(ReleaseMigrationRequirement)
                .where(ReleaseMigrationRequirement.release_id == release_id)
                .order_by(ReleaseMigrationRequirement.created_at.asc())
            ).all()
        )

    def get_rollback_target(self, release_id: uuid.UUID) -> ReleaseRollbackTarget | None:
        return self.db.scalar(select(ReleaseRollbackTarget).where(ReleaseRollbackTarget.release_id == release_id))

    def latest_acceptance(self, release_id: uuid.UUID) -> ReleaseAcceptanceEvidence | None:
        return self.db.scalar(
            select(ReleaseAcceptanceEvidence)
            .where(ReleaseAcceptanceEvidence.release_id == release_id)
            .order_by(ReleaseAcceptanceEvidence.evaluated_at.desc())
            .limit(1)
        )
