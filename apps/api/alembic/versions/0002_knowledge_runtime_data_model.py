"""knowledge runtime data model

Revision ID: 0002_knowledge_runtime_data_model
Revises: 0001_platform_foundation
Create Date: 2026-06-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_knowledge_runtime_data_model"
down_revision: Union[str, None] = "0001_platform_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "document_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="registered"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["documents.collections.id"]),
        sa.ForeignKeyConstraint(["document_type_id"], ["documents.document_types.id"]),
        sa.ForeignKeyConstraint(["metadata_template_id"], ["documents.metadata_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "external_reference", name="uq_document_records_org_external_reference"),
        schema="documents",
    )
    op.create_index("ix_document_records_organization_id", "document_records", ["organization_id"], schema="documents")
    op.create_index("ix_document_records_collection_id", "document_records", ["collection_id"], schema="documents")
    op.create_index("ix_document_records_status", "document_records", ["status"], schema="documents")

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(length=128), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("object_store_provider", sa.String(length=64), nullable=True),
        sa.Column("object_store_bucket", sa.String(length=255), nullable=True),
        sa.Column("object_store_key", sa.String(length=1024), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="registered"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_record_id", "version_number", name="uq_document_versions_record_version"),
        schema="documents",
    )
    op.create_index("ix_document_versions_organization_id", "document_versions", ["organization_id"], schema="documents")
    op.create_index("ix_document_versions_document_record_id", "document_versions", ["document_record_id"], schema="documents")
    op.create_index("ix_document_versions_checksum_sha256", "document_versions", ["checksum_sha256"], schema="documents")

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("pipeline_name", sa.String(length=128), nullable=True),
        sa.Column("pipeline_version", sa.String(length=64), nullable=True),
        sa.Column("adapter_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("chunking_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quality_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("publication_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"]),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.connectors.id"]),
        sa.ForeignKeyConstraint(["connector_run_id"], ["connectors.connector_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )
    op.create_index("ix_ingestion_jobs_status_priority_created", "ingestion_jobs", ["status", "priority", "created_at"], schema="documents")
    op.create_index("ix_ingestion_jobs_organization_status", "ingestion_jobs", ["organization_id", "status"], schema="documents")
    op.create_index("ix_ingestion_jobs_document_version_id", "ingestion_jobs", ["document_version_id"], schema="documents")
    op.create_index("ix_ingestion_jobs_connector_run_id", "ingestion_jobs", ["connector_run_id"], schema="documents")

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column("object_store_provider", sa.String(length=64), nullable=True),
        sa.Column("bucket", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"]),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["documents.ingestion_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )
    op.create_index("ix_artifacts_organization_id", "artifacts", ["organization_id"], schema="documents")
    op.create_index("ix_artifacts_document_version_id", "artifacts", ["document_version_id"], schema="documents")
    op.create_index("ix_artifacts_ingestion_job_id", "artifacts", ["ingestion_job_id"], schema="documents")
    op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"], schema="documents")
    op.create_index("ix_artifacts_status", "artifacts", ["status"], schema="documents")

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_key", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.Column("section_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fts_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["documents.artifacts.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["documents.collections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "chunk_index", name="uq_chunks_version_index"),
        schema="documents",
    )
    op.create_index("ix_chunks_organization_id", "chunks", ["organization_id"], schema="documents")
    op.create_index("ix_chunks_collection_status", "chunks", ["collection_id", "status"], schema="documents")
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"], schema="documents")
    op.create_index("ix_chunks_semantic_hash", "chunks", ["semantic_hash"], schema="documents")
    op.create_index("ix_chunks_fts_vector", "chunks", ["fts_vector"], unique=False, schema="documents", postgresql_using="gin")

    op.create_table(
        "indexing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("index_target", sa.String(length=64), nullable=False),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vector_provider", sa.String(length=64), nullable=True),
        sa.Column("vector_collection_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["documents.collections.id"]),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"]),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["documents.ingestion_jobs.id"]),
        sa.ForeignKeyConstraint(["embedding_model_id"], ["ai.models.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )
    op.create_index("ix_indexing_jobs_organization_status", "indexing_jobs", ["organization_id", "status"], schema="documents")
    op.create_index("ix_indexing_jobs_collection_id", "indexing_jobs", ["collection_id"], schema="documents")
    op.create_index("ix_indexing_jobs_document_version_id", "indexing_jobs", ["document_version_id"], schema="documents")
    op.create_index("ix_indexing_jobs_ingestion_job_id", "indexing_jobs", ["ingestion_job_id"], schema="documents")
    op.create_index("ix_indexing_jobs_embedding_model_id", "indexing_jobs", ["embedding_model_id"], schema="documents")


def downgrade() -> None:
    op.drop_index("ix_indexing_jobs_embedding_model_id", table_name="indexing_jobs", schema="documents")
    op.drop_index("ix_indexing_jobs_ingestion_job_id", table_name="indexing_jobs", schema="documents")
    op.drop_index("ix_indexing_jobs_document_version_id", table_name="indexing_jobs", schema="documents")
    op.drop_index("ix_indexing_jobs_collection_id", table_name="indexing_jobs", schema="documents")
    op.drop_index("ix_indexing_jobs_organization_status", table_name="indexing_jobs", schema="documents")
    op.drop_table("indexing_jobs", schema="documents")

    op.drop_index("ix_chunks_fts_vector", table_name="chunks", schema="documents")
    op.drop_index("ix_chunks_semantic_hash", table_name="chunks", schema="documents")
    op.drop_index("ix_chunks_content_hash", table_name="chunks", schema="documents")
    op.drop_index("ix_chunks_collection_status", table_name="chunks", schema="documents")
    op.drop_index("ix_chunks_organization_id", table_name="chunks", schema="documents")
    op.drop_table("chunks", schema="documents")

    op.drop_index("ix_artifacts_status", table_name="artifacts", schema="documents")
    op.drop_index("ix_artifacts_artifact_type", table_name="artifacts", schema="documents")
    op.drop_index("ix_artifacts_ingestion_job_id", table_name="artifacts", schema="documents")
    op.drop_index("ix_artifacts_document_version_id", table_name="artifacts", schema="documents")
    op.drop_index("ix_artifacts_organization_id", table_name="artifacts", schema="documents")
    op.drop_table("artifacts", schema="documents")

    op.drop_index("ix_ingestion_jobs_connector_run_id", table_name="ingestion_jobs", schema="documents")
    op.drop_index("ix_ingestion_jobs_document_version_id", table_name="ingestion_jobs", schema="documents")
    op.drop_index("ix_ingestion_jobs_organization_status", table_name="ingestion_jobs", schema="documents")
    op.drop_index("ix_ingestion_jobs_status_priority_created", table_name="ingestion_jobs", schema="documents")
    op.drop_table("ingestion_jobs", schema="documents")

    op.drop_index("ix_document_versions_checksum_sha256", table_name="document_versions", schema="documents")
    op.drop_index("ix_document_versions_document_record_id", table_name="document_versions", schema="documents")
    op.drop_index("ix_document_versions_organization_id", table_name="document_versions", schema="documents")
    op.drop_table("document_versions", schema="documents")

    op.drop_index("ix_document_records_status", table_name="document_records", schema="documents")
    op.drop_index("ix_document_records_collection_id", table_name="document_records", schema="documents")
    op.drop_index("ix_document_records_organization_id", table_name="document_records", schema="documents")
    op.drop_table("document_records", schema="documents")
