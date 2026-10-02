"""add governed release artifact runtime

Revision ID: 20260714_920
Revises: 20260713_910
Create Date: 2026-07-14 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260714_920"
down_revision = "20260713_910"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "governed_releases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("release_code", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("edition", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("source_repository", sa.String(255), nullable=False),
        sa.Column("source_revision", sa.String(128), nullable=False),
        sa.Column("source_branch", sa.String(128)),
        sa.Column("created_by", sa.String(255)),
        sa.Column("prepared_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64)),
        *_timestamps(),
        sa.CheckConstraint("edition IN ('community','enterprise')", name="ck_runtime_governed_releases_edition"),
        sa.CheckConstraint(
            "channel IN ('development','acceptance','release_candidate','stable')",
            name="ck_runtime_governed_releases_channel",
        ),
        sa.CheckConstraint(
            "status IN ('draft','assembling','ready_for_validation','validated','approved',"
            "'superseded','retired','blocked')",
            name="ck_runtime_governed_releases_status",
        ),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_governed_releases_input_hash"),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_governed_releases_result_hash"
        ),
        sa.UniqueConstraint("release_code", name="uq_runtime_governed_releases_code"),
        sa.UniqueConstraint("idempotency_key", name="uq_runtime_governed_releases_idempotency"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_governed_releases_version", "governed_releases", ["version", "edition", "channel"], schema="runtime"
    )
    op.create_index(
        "ix_runtime_governed_releases_status", "governed_releases", ["status", "created_at"], schema="runtime"
    )

    op.create_table(
        "release_builds",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("build_number", sa.String(64), nullable=False),
        sa.Column("build_status", sa.String(32), server_default="planned", nullable=False),
        sa.Column("build_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("builder_type", sa.String(32), nullable=False),
        sa.Column("builder_reference", sa.String(255)),
        sa.Column("source_revision", sa.String(128), nullable=False),
        sa.Column("target_platform", sa.String(32), nullable=False),
        sa.Column("target_architecture", sa.String(32), nullable=False),
        sa.Column("build_profile", sa.String(128), nullable=False),
        sa.Column("reproducible", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reproducibility_evidence", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "build_status IN ('planned','running','completed','failed','cancelled','blocked')",
            name="ck_runtime_release_builds_status",
        ),
        sa.CheckConstraint(
            "builder_type IN ('local','ci','external','manual_evidence')", name="ck_runtime_release_builds_builder"
        ),
        sa.CheckConstraint(
            "target_platform IN ('linux','darwin','windows','container','other')",
            name="ck_runtime_release_builds_platform",
        ),
        sa.CheckConstraint(
            "target_architecture IN ('amd64','arm64','multi_arch','other')", name="ck_runtime_release_builds_arch"
        ),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_runtime_release_builds_input_hash"),
        sa.CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64", name="ck_runtime_release_builds_result_hash"
        ),
        sa.UniqueConstraint("release_id", "build_number", name="uq_runtime_release_build_number"),
        sa.UniqueConstraint("release_id", "idempotency_key", name="uq_runtime_release_build_idempotency"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_builds_release", "release_builds", ["release_id", "created_at"], schema="runtime"
    )
    op.create_index(
        "ix_runtime_release_builds_status", "release_builds", ["build_status", "build_timestamp"], schema="runtime"
    )

    op.create_table(
        "release_build_manifests",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("build_id", UUID, sa.ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_version", sa.String(64), nullable=False),
        sa.Column("application_version", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.String(128), nullable=False),
        sa.Column("build_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("python_version", sa.String(64)),
        sa.Column("node_version", sa.String(64)),
        sa.Column("database_schema_revision", sa.String(128), nullable=False),
        sa.Column("container_runtime", sa.String(128)),
        sa.Column("target_platforms", JSONB, nullable=False),
        sa.Column("target_architectures", JSONB, nullable=False),
        sa.Column("dependency_summary", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("component_versions", JSONB, nullable=False),
        sa.Column("configuration_profile", sa.String(128), nullable=False),
        sa.Column("manifest_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_runtime_release_build_manifest_hash"),
        sa.UniqueConstraint("build_id", name="uq_runtime_release_build_manifest_build"),
        sa.UniqueConstraint("manifest_hash", name="uq_runtime_release_build_manifest_hash"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_build_manifest_build",
        "release_build_manifests",
        ["build_id", "created_at"],
        schema="runtime",
    )

    op.create_table(
        "release_deployment_manifests",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("build_id", UUID, sa.ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_version", sa.String(64), nullable=False),
        sa.Column("deployment_profile", sa.String(32), nullable=False),
        sa.Column("deployment_strategy", sa.String(32), nullable=False),
        sa.Column("required_services", JSONB, nullable=False),
        sa.Column("optional_services", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("health_checks", JSONB, nullable=False),
        sa.Column("readiness_checks", JSONB, nullable=False),
        sa.Column("startup_order", JSONB, nullable=False),
        sa.Column("configuration_requirements", JSONB, nullable=False),
        sa.Column("secret_requirements", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("storage_requirements", JSONB, nullable=False),
        sa.Column("network_requirements", JSONB, nullable=False),
        sa.Column("resource_requirements", JSONB, nullable=False),
        sa.Column("migration_requirements", JSONB, nullable=False),
        sa.Column(
            "rollback_target_release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="RESTRICT")
        ),
        sa.Column("rollback_procedure_reference", sa.String(255)),
        sa.Column("manifest_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "deployment_profile IN ('local','on_premise','hybrid','cloud')",
            name="ck_runtime_release_deployment_profile",
        ),
        sa.CheckConstraint(
            "deployment_strategy IN ('recreate','rolling','blue_green','external')",
            name="ck_runtime_release_deployment_strategy",
        ),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_runtime_release_deployment_manifest_hash"),
        sa.UniqueConstraint("release_id", name="uq_runtime_release_deployment_manifest_release"),
        sa.UniqueConstraint("manifest_hash", name="uq_runtime_release_deployment_manifest_hash"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_deployment_manifest_release",
        "release_deployment_manifests",
        ["release_id", "build_id"],
        schema="runtime",
    )

    op.create_table(
        "release_artifacts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("build_id", UUID, sa.ForeignKey("runtime.release_builds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_code", sa.String(128), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("component", sa.String(128), nullable=False),
        sa.Column("edition", sa.String(32), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("architecture", sa.String(32), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("artifact_reference", sa.String(512), nullable=False),
        sa.Column("artifact_location_masked", sa.String(512)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("checksum_algorithm", sa.String(32)),
        sa.Column("checksum", sa.String(256)),
        sa.Column("digest_algorithm", sa.String(32)),
        sa.Column("digest", sa.String(256)),
        sa.Column("signature_status", sa.String(32), server_default="not_provided", nullable=False),
        sa.Column("provenance_status", sa.String(32), server_default="not_provided", nullable=False),
        sa.Column("sbom_status", sa.String(32), server_default="not_provided", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("status", sa.String(32), server_default="registered", nullable=False),
        sa.Column("metadata_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("edition IN ('community','enterprise')", name="ck_runtime_release_artifacts_edition"),
        sa.CheckConstraint(
            "artifact_type IN ('container_image','source_bundle','portal_bundle','python_package',"
            "'migration_bundle','configuration_template','sbom','signature','provenance','release_notes',"
            "'compatibility_manifest','deployment_manifest','other')",
            name="ck_runtime_release_artifacts_type",
        ),
        sa.CheckConstraint(
            "status IN ('registered','verified','failed','superseded','missing')",
            name="ck_runtime_release_artifacts_status",
        ),
        sa.CheckConstraint(
            "signature_status IN ('not_provided','pending','verified','failed','not_applicable')",
            name="ck_runtime_release_artifacts_signature",
        ),
        sa.CheckConstraint(
            "provenance_status IN ('not_provided','pending','verified','failed')",
            name="ck_runtime_release_artifacts_provenance",
        ),
        sa.CheckConstraint(
            "sbom_status IN ('not_provided','pending','available','verified','failed')",
            name="ck_runtime_release_artifacts_sbom",
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_release_artifacts_size"),
        sa.CheckConstraint(
            "NOT required OR checksum IS NOT NULL OR digest IS NOT NULL",
            name="ck_runtime_release_artifacts_required_digest",
        ),
        sa.UniqueConstraint("release_id", "build_id", "artifact_code", name="uq_runtime_release_artifact_code"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_artifacts_release", "release_artifacts", ["release_id", "build_id"], schema="runtime"
    )
    op.create_index(
        "ix_runtime_release_artifacts_status", "release_artifacts", ["status", "required"], schema="runtime"
    )

    op.create_table(
        "release_compatibility",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("compatibility_type", sa.String(64), nullable=False),
        sa.Column("minimum_version", sa.String(128)),
        sa.Column("maximum_version", sa.String(128)),
        sa.Column("compatible", sa.Boolean(), nullable=False),
        sa.Column("requirements", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence_payload", JSONB, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_compatibility_hash"),
        sa.CheckConstraint(
            "compatibility_type IN ('database_schema','previous_release','postgresql','redis','object_storage',"
            "'python','node','browser','operating_system','container_runtime','other')",
            name="ck_runtime_release_compatibility_type",
        ),
        sa.UniqueConstraint(
            "release_id",
            "compatibility_type",
            "minimum_version",
            "maximum_version",
            name="uq_runtime_release_compatibility_range",
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_compatibility_evidence"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_compatibility_release",
        "release_compatibility",
        ["release_id", "compatibility_type"],
        schema="runtime",
    )

    op.create_table(
        "release_migration_requirements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("from_revision", sa.String(128)),
        sa.Column("to_revision", sa.String(128), nullable=False),
        sa.Column("migration_required", sa.Boolean(), nullable=False),
        sa.Column("migration_strategy", sa.String(32), nullable=False),
        sa.Column("reversible", sa.Boolean(), nullable=False),
        sa.Column("irreversible_reason", sa.Text()),
        sa.Column("preconditions", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("postconditions", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence_payload", JSONB, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "migration_strategy IN ('none','forward_only','expand_contract','offline','external')",
            name="ck_runtime_release_migration_strategy",
        ),
        sa.CheckConstraint(
            "reversible OR irreversible_reason IS NOT NULL", name="ck_runtime_release_migration_irreversible_reason"
        ),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_migration_hash"),
        sa.UniqueConstraint(
            "release_id",
            "from_revision",
            "to_revision",
            name="uq_runtime_release_migration_path",
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_migration_evidence"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_migration_release",
        "release_migration_requirements",
        ["release_id", "to_revision"],
        schema="runtime",
    )

    op.create_table(
        "release_rollback_targets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "rollback_target_release_id",
            UUID,
            sa.ForeignKey("runtime.governed_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rollback_supported", sa.Boolean(), nullable=False),
        sa.Column("rollback_strategy", sa.String(64), nullable=False),
        sa.Column("database_rollback_supported", sa.Boolean(), nullable=False),
        sa.Column("application_rollback_supported", sa.Boolean(), nullable=False),
        sa.Column("required_actions", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("blockers", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence_payload", JSONB, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("release_id <> rollback_target_release_id", name="ck_runtime_release_rollback_not_self"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_rollback_hash"),
        sa.UniqueConstraint("release_id", name="uq_runtime_release_rollback_target_release"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_rollback_target",
        "release_rollback_targets",
        ["release_id", "rollback_target_release_id"],
        schema="runtime",
    )

    op.create_table(
        "release_acceptance_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "release_id", UUID, sa.ForeignKey("runtime.governed_releases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        *[
            sa.Column(name, sa.Boolean(), nullable=False)
            for name in (
                "build_manifest_valid",
                "deployment_manifest_valid",
                "required_artifacts_present",
                "required_artifacts_verified",
                "checksums_valid",
                "digests_valid",
                "provenance_available",
                "sbom_available",
                "compatibility_valid",
                "migration_requirements_valid",
                "rollback_target_valid",
                "edition_boundary_valid",
            )
        ],
        sa.Column("blockers", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("warnings", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence_payload", JSONB, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed','failed','blocked','not_evaluated')", name="ck_runtime_release_acceptance_status"
        ),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_runtime_release_acceptance_hash"),
        sa.CheckConstraint("length(result_hash) = 64", name="ck_runtime_release_acceptance_result_hash"),
        sa.UniqueConstraint("release_id", "evidence_hash", name="uq_runtime_release_acceptance_evidence"),
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_acceptance_release",
        "release_acceptance_evidence",
        ["release_id", "evaluated_at"],
        schema="runtime",
    )
    op.create_index(
        "ix_runtime_release_acceptance_status",
        "release_acceptance_evidence",
        ["status", "evaluated_at"],
        schema="runtime",
    )


def downgrade() -> None:
    for table in (
        "release_acceptance_evidence",
        "release_rollback_targets",
        "release_migration_requirements",
        "release_compatibility",
        "release_artifacts",
        "release_deployment_manifests",
        "release_build_manifests",
        "release_builds",
        "governed_releases",
    ):
        op.drop_table(table, schema="runtime")
