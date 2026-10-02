import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentType(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_document_types_org_code"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class MetadataTemplate(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "metadata_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_metadata_templates_org_code"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_types.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_definition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class RetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "retention_policies"
    __table_args__ = {"schema": "documents"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class ClassificationRule(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "classification_rules"
    __table_args__ = {"schema": "documents"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_collections_org_code"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    vector_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vector_collection_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class DocumentRecord(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_records"
    __table_args__ = (
        Index("ix_document_records_organization_id", "organization_id"),
        Index("ix_document_records_collection_id", "collection_id"),
        Index("ix_document_records_status", "status"),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_document_records_organization_identity",
        ),
        UniqueConstraint("organization_id", "external_reference", name="uq_document_records_org_external_reference"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.collections.id"), nullable=True
    )
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_types.id"), nullable=True
    )
    metadata_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.metadata_templates.id"), nullable=True
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    classification: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="registered", nullable=False)


class DocumentOrganizationAssociationAggregate(TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_organization_association_aggregates"
    __table_args__ = (
        CheckConstraint(
            "revision >= 0",
            name="document_organization_association_revision",
        ),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            [
                "documents.document_records.organization_id",
                "documents.document_records.id",
            ],
            name="fk_document_organization_aggregate_document",
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_mutation_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DocumentOrganizationAssociation(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_organization_associations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="document_organization_association_status",
        ),
        ForeignKeyConstraint(
            ["organization_id", "document_id"],
            [
                "documents.document_records.organization_id",
                "documents.document_records.id",
            ],
            name="fk_document_organization_association_document",
        ),
        ForeignKeyConstraint(
            ["organization_id", "organization_node_id"],
            [
                "core.organization_nodes.organization_id",
                "core.organization_nodes.id",
            ],
            name="fk_document_organization_association_node",
        ),
        UniqueConstraint(
            "organization_id",
            "document_id",
            "organization_node_id",
            name="uq_document_organization_association_identity",
        ),
        Index(
            "ix_document_organization_associations_document_status",
            "organization_id",
            "document_id",
            "status",
        ),
        Index(
            "ix_document_organization_associations_node_status",
            "organization_id",
            "organization_node_id",
            "status",
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    archived_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(), nullable=True)
    restored_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[str | None] = mapped_column(String(), nullable=True)


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_record_id", "version_number", name="uq_document_versions_record_version"),
        Index("ix_document_versions_organization_id", "organization_id"),
        Index("ix_document_versions_document_record_id", "document_record_id"),
        Index("ix_document_versions_checksum_sha256", "checksum_sha256"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    document_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_store_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_store_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_store_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="registered", nullable=False)


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_status_priority_created", "status", "priority", "created_at"),
        Index("ix_ingestion_jobs_organization_status", "organization_id", "status"),
        Index("ix_ingestion_jobs_document_version_id", "document_version_id"),
        Index("ix_ingestion_jobs_connector_run_id", "connector_run_id"),
        Index("uq_ingestion_jobs_runtime_execution", "runtime_execution_id", unique=True),
        ForeignKeyConstraint(
            ["organization_id", "runtime_execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_ingestion_jobs_runtime_execution",
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    runtime_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=True
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_versions.id"), nullable=True
    )
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.connectors.id"), nullable=True
    )
    connector_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.connector_runs.id"), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adapter_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    chunking_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    quality_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    publication_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    locked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_organization_id", "organization_id"),
        Index("ix_artifacts_document_version_id", "document_version_id"),
        Index("ix_artifacts_ingestion_job_id", "ingestion_job_id"),
        Index("ix_artifacts_artifact_type", "artifact_type"),
        Index("ix_artifacts_status", "status"),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    document_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_versions.id"), nullable=False
    )
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.ingestion_jobs.id"), nullable=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_store_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_chunks_version_index"),
        Index("ix_chunks_organization_id", "organization_id"),
        Index("ix_chunks_collection_status", "collection_id", "status"),
        Index("ix_chunks_processing_revision_id", "processing_revision_id"),
        Index("ix_chunks_content_hash", "content_hash"),
        Index("ix_chunks_semantic_hash", "semantic_hash"),
        Index("ix_chunks_fts_vector", "fts_vector", postgresql_using="gin"),
        Index(
            "uq_chunks_revision_chunk_key",
            "organization_id",
            "processing_revision_id",
            "chunk_key",
            unique=True,
            postgresql_where=text("processing_revision_id IS NOT NULL"),
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    document_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_versions.id"), nullable=False
    )
    processing_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.processing_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.artifacts.id"), nullable=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.collections.id"), nullable=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_ref: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    quality: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    fts_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)


class IndexingJob(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "indexing_jobs"
    __table_args__ = (
        Index("ix_indexing_jobs_organization_status", "organization_id", "status"),
        Index("ix_indexing_jobs_collection_id", "collection_id"),
        Index("ix_indexing_jobs_document_version_id", "document_version_id"),
        Index("ix_indexing_jobs_ingestion_job_id", "ingestion_job_id"),
        Index("ix_indexing_jobs_embedding_model_id", "embedding_model_id"),
        Index("uq_indexing_jobs_runtime_execution", "runtime_execution_id", unique=True),
        ForeignKeyConstraint(
            ["organization_id", "runtime_execution_id"],
            ["runtime.executions.organization_id", "runtime.executions.id"],
            name="fk_indexing_jobs_runtime_execution",
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    runtime_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.collections.id"), nullable=True
    )
    document_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_records.id"), nullable=True
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_versions.id"), nullable=True
    )
    ingestion_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.ingestion_jobs.id"), nullable=True
    )
    index_target: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.models.id"), nullable=True
    )
    vector_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vector_collection_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
