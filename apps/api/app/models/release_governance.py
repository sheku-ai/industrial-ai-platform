from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from app.db.base import Base


class GovernedRelease(Base):
    __tablename__ = "governed_releases"
    __table_args__ = (
        UniqueConstraint("release_code", name="uq_runtime_governed_releases_code"),
        UniqueConstraint("idempotency_key", name="uq_runtime_governed_releases_idempotency"),
        CheckConstraint("edition IN ('community','enterprise')", name="ck_runtime_governed_releases_edition"),
        CheckConstraint(
            "channel IN ('development','acceptance','release_candidate','stable')",
            name="ck_runtime_governed_releases_channel",
        ),
        CheckConstraint(
            "status IN ('draft','assembling','ready_for_validation','validated','approved',"
            "'superseded','retired','blocked')",
            name="ck_runtime_governed_releases_status",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_governed_releases_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_governed_releases_result_hash"
        ),
        Index("ix_runtime_governed_releases_version", "version", "edition", "channel"),
        Index("ix_runtime_governed_releases_status", "status", "created_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_code: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    edition: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="draft", nullable=False)
    source_repository: Mapped[str] = mapped_column(String(255), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    source_branch: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(String(255))
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReleaseBuild(Base):
    __tablename__ = "release_builds"
    __table_args__ = (
        UniqueConstraint("release_id", "build_number", name="uq_runtime_release_build_number"),
        UniqueConstraint("release_id", "idempotency_key", name="uq_runtime_release_build_idempotency"),
        CheckConstraint(
            "build_status IN ('planned','running','completed','failed','cancelled','blocked')",
            name="ck_runtime_release_builds_status",
        ),
        CheckConstraint(
            "builder_type IN ('local','ci','external','manual_evidence')", name="ck_runtime_release_builds_builder"
        ),
        CheckConstraint(
            "target_platform IN ('linux','darwin','windows','container','other')",
            name="ck_runtime_release_builds_platform",
        ),
        CheckConstraint(
            "target_architecture IN ('amd64','arm64','multi_arch','other')", name="ck_runtime_release_builds_arch"
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_runtime_release_builds_input_hash"),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_release_builds_result_hash"
        ),
        Index("ix_runtime_release_builds_release", "release_id", "created_at"),
        Index("ix_runtime_release_builds_status", "build_status", "build_timestamp"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    build_number: Mapped[str] = mapped_column(String(64), nullable=False)
    build_status: Mapped[str] = mapped_column(String(32), server_default="planned", nullable=False)
    build_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    builder_type: Mapped[str] = mapped_column(String(32), nullable=False)
    builder_reference: Mapped[str | None] = mapped_column(String(255))
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    target_architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    build_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    reproducible: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    reproducibility_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReleaseBuildManifest(Base):
    __tablename__ = "release_build_manifests"
    __table_args__ = (
        UniqueConstraint("build_id", name="uq_runtime_release_build_manifest_build"),
        UniqueConstraint("manifest_hash", name="uq_runtime_release_build_manifest_hash"),
        CheckConstraint("length(manifest_hash) = 64", name="ck_runtime_release_build_manifest_hash"),
        Index("ix_runtime_release_build_manifest_build", "build_id", "created_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False
    )
    manifest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    build_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    python_version: Mapped[str | None] = mapped_column(String(64))
    node_version: Mapped[str | None] = mapped_column(String(64))
    database_schema_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    container_runtime: Mapped[str | None] = mapped_column(String(128))
    target_platforms: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    target_architectures: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    dependency_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    component_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    configuration_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReleaseDeploymentManifest(Base):
    __tablename__ = "release_deployment_manifests"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_runtime_release_deployment_manifest_release"),
        UniqueConstraint("manifest_hash", name="uq_runtime_release_deployment_manifest_hash"),
        CheckConstraint(
            "deployment_profile IN ('local','on_premise','hybrid','cloud')",
            name="ck_runtime_release_deployment_profile",
        ),
        CheckConstraint(
            "deployment_strategy IN ('recreate','rolling','blue_green','external')",
            name="ck_runtime_release_deployment_strategy",
        ),
        CheckConstraint("length(manifest_hash) = 64", name="ck_runtime_release_deployment_manifest_hash"),
        Index("ix_runtime_release_deployment_manifest_release", "release_id", "build_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False
    )
    manifest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    deployment_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    required_services: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    optional_services: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    health_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    readiness_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    startup_order: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    configuration_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    secret_requirements: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    storage_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    network_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resource_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    migration_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rollback_target_release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="RESTRICT")
    )
    rollback_procedure_reference: Mapped[str | None] = mapped_column(String(255))
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReleaseArtifact(Base):
    __tablename__ = "release_artifacts"
    __table_args__ = (
        UniqueConstraint("release_id", "build_id", "artifact_code", name="uq_runtime_release_artifact_code"),
        CheckConstraint("edition IN ('community','enterprise')", name="ck_runtime_release_artifacts_edition"),
        CheckConstraint(
            "artifact_type IN ('container_image','source_bundle','portal_bundle','python_package','migration_bundle',"
            "'configuration_template','sbom','signature','provenance','release_notes','compatibility_manifest',"
            "'deployment_manifest','other')",
            name="ck_runtime_release_artifacts_type",
        ),
        CheckConstraint(
            "status IN ('registered','verified','failed','superseded','missing')",
            name="ck_runtime_release_artifacts_status",
        ),
        CheckConstraint(
            "signature_status IN ('not_provided','pending','verified','failed','not_applicable')",
            name="ck_runtime_release_artifacts_signature",
        ),
        CheckConstraint(
            "provenance_status IN ('not_provided','pending','verified','failed')",
            name="ck_runtime_release_artifacts_provenance",
        ),
        CheckConstraint(
            "sbom_status IN ('not_provided','pending','available','verified','failed')",
            name="ck_runtime_release_artifacts_sbom",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_release_artifacts_size"),
        CheckConstraint(
            "NOT required OR checksum IS NOT NULL OR digest IS NOT NULL",
            name="ck_runtime_release_artifacts_required_digest",
        ),
        Index("ix_runtime_release_artifacts_release", "release_id", "build_id"),
        Index("ix_runtime_release_artifacts_status", "status", "required"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False
    )
    artifact_code: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    edition: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_location_masked: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(32))
    checksum: Mapped[str | None] = mapped_column(String(256))
    digest_algorithm: Mapped[str | None] = mapped_column(String(32))
    digest: Mapped[str | None] = mapped_column(String(256))
    signature_status: Mapped[str] = mapped_column(String(32), server_default="not_provided", nullable=False)
    provenance_status: Mapped[str] = mapped_column(String(32), server_default="not_provided", nullable=False)
    sbom_status: Mapped[str] = mapped_column(String(32), server_default="not_provided", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="registered", nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseCompatibility(Base):
    __tablename__ = "release_compatibility"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "compatibility_type",
            "minimum_version",
            "maximum_version",
            name="uq_runtime_release_compatibility_range",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_compatibility_evidence"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_compatibility_hash"),
        CheckConstraint(
            "compatibility_type IN ('database_schema','previous_release','postgresql','redis','object_storage',"
            "'python','node','browser','operating_system','container_runtime','other')",
            name="ck_runtime_release_compatibility_type",
        ),
        Index("ix_runtime_release_compatibility_release", "release_id", "compatibility_type"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    compatibility_type: Mapped[str] = mapped_column(String(64), nullable=False)
    minimum_version: Mapped[str | None] = mapped_column(String(128))
    maximum_version: Mapped[str | None] = mapped_column(String(128))
    compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReleaseMigrationRequirement(Base):
    __tablename__ = "release_migration_requirements"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "from_revision",
            "to_revision",
            name="uq_runtime_release_migration_path",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_migration_evidence"),
        CheckConstraint(
            "migration_strategy IN ('none','forward_only','expand_contract','offline','external')",
            name="ck_runtime_release_migration_strategy",
        ),
        CheckConstraint(
            "reversible OR irreversible_reason IS NOT NULL", name="ck_runtime_release_migration_irreversible_reason"
        ),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_migration_hash"),
        Index("ix_runtime_release_migration_release", "release_id", "to_revision"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    from_revision: Mapped[str | None] = mapped_column(String(128))
    to_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    migration_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    migration_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    irreversible_reason: Mapped[str | None] = mapped_column(Text)
    preconditions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    postconditions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReleaseRollbackTarget(Base):
    __tablename__ = "release_rollback_targets"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_runtime_release_rollback_target_release"),
        CheckConstraint(
            "release_id IS NULL OR rollback_target_release_id IS NULL OR release_id <> rollback_target_release_id",
            name=conv("ck_runtime_release_rollback_not_self"),
        ),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_rollback_hash"),
        Index("ix_runtime_release_rollback_target", "release_id", "rollback_target_release_id"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    rollback_target_release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="RESTRICT"), nullable=False
    )
    rollback_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rollback_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    database_rollback_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    application_rollback_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseAcceptanceEvidence(Base):
    __tablename__ = "release_acceptance_evidence"
    __table_args__ = (
        UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_acceptance_evidence"),
        CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')", name="ck_runtime_release_acceptance_status"
        ),
        CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_acceptance_hash"),
        CheckConstraint("length(result_hash) = 64", name="ck_runtime_release_acceptance_result_hash"),
        Index("ix_runtime_release_acceptance_release", "release_id", "evaluated_at"),
        Index("ix_runtime_release_acceptance_status", "status", "evaluated_at"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    build_manifest_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deployment_manifest_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_artifacts_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_artifacts_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checksums_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    digests_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provenance_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sbom_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    compatibility_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    migration_requirements_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rollback_target_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    edition_boundary_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
