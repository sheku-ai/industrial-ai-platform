"""add protected document review tables

Revision ID: 20260621_2506a
Revises: 20260621_0040
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260621_2506a"
down_revision: Union[str, None] = "20260621_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_review_cases",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("detected_format", sa.String(length=128), nullable=False),
        sa.Column("detected_by", sa.String(length=128), nullable=False),
        sa.Column("encryption_type", sa.String(length=128), nullable=True),
        sa.Column("allowed_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_reference", sa.String(length=1024), nullable=True),
        sa.Column("secret_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secret_single_use", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["document_record_id"], ["documents.document_records.id"], name="fk_document_review_cases_document_record_id_document_records"),
        sa.ForeignKeyConstraint(["document_version_id"], ["documents.document_versions.id"], name="fk_document_review_cases_document_version_id_document_versions"),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["documents.ingestion_jobs.id"], name="fk_document_review_cases_ingestion_job_id_ingestion_jobs"),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_document_review_cases_organization_id_organizations"),
        sa.PrimaryKeyConstraint("id", name="pk_document_review_cases"),
        schema="documents",
    )
    op.create_index("ix_document_review_cases_document_version", "document_review_cases", ["document_version_id"], unique=False, schema="documents")
    op.create_index("ix_document_review_cases_expires_at", "document_review_cases", ["expires_at"], unique=False, schema="documents")
    op.create_index("ix_document_review_cases_org_status", "document_review_cases", ["organization_id", "status"], unique=False, schema="documents")

    op.create_table(
        "document_review_events",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_document_review_events_organization_id_organizations"),
        sa.ForeignKeyConstraint(["review_case_id"], ["documents.document_review_cases.id"], name="fk_document_review_events_review_case_id_document_review_cases", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_document_review_events"),
        schema="documents",
    )
    op.create_index("ix_document_review_events_organization", "document_review_events", ["organization_id"], unique=False, schema="documents")
    op.create_index("ix_document_review_events_review_created", "document_review_events", ["review_case_id", "created_at"], unique=False, schema="documents")


def downgrade() -> None:
    op.drop_index("ix_document_review_events_review_created", table_name="document_review_events", schema="documents")
    op.drop_index("ix_document_review_events_organization", table_name="document_review_events", schema="documents")
    op.drop_table("document_review_events", schema="documents")
    op.drop_index("ix_document_review_cases_org_status", table_name="document_review_cases", schema="documents")
    op.drop_index("ix_document_review_cases_expires_at", table_name="document_review_cases", schema="documents")
    op.drop_index("ix_document_review_cases_document_version", table_name="document_review_cases", schema="documents")
    op.drop_table("document_review_cases", schema="documents")
