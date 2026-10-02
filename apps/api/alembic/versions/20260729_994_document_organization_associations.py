"""Add authoritative document to organization node associations.

Revision ID: 20260729_994
Revises: 20260729_993
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_994"
down_revision: str | None = "20260729_993"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_document_records_organization_identity",
        "document_records",
        ["organization_id", "id"],
        schema="documents",
    )
    op.create_unique_constraint(
        "uq_organization_nodes_organization_identity",
        "organization_nodes",
        ["organization_id", "id"],
        schema="core",
    )

    op.create_table(
        "document_organization_association_aggregates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_mutation_key", sa.String(length=255), nullable=True),
        sa.Column("last_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_documents_document_organization_association_revision",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            [
                "documents.document_records.organization_id",
                "documents.document_records.id",
            ],
            name="fk_document_organization_aggregate_document",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "document_id",
            name="pk_document_organization_association_aggregates",
        ),
        schema="documents",
    )

    op.create_table(
        "document_organization_associations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.String(), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_documents_document_organization_association_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            [
                "documents.document_records.organization_id",
                "documents.document_records.id",
            ],
            name="fk_document_organization_association_document",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "organization_node_id"],
            [
                "core.organization_nodes.organization_id",
                "core.organization_nodes.id",
            ],
            name="fk_document_organization_association_node",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "document_id",
            "organization_node_id",
            name="uq_document_organization_association_identity",
        ),
        schema="documents",
    )
    op.create_index(
        "ix_document_organization_associations_document_status",
        "document_organization_associations",
        ["organization_id", "document_id", "status"],
        schema="documents",
    )
    op.create_index(
        "ix_document_organization_associations_node_status",
        "document_organization_associations",
        ["organization_id", "organization_node_id", "status"],
        schema="documents",
    )

    op.execute(
        """
        INSERT INTO documents.document_organization_association_aggregates (
            organization_id,
            document_id,
            revision,
            created_at,
            updated_at,
            created_by,
            updated_by
        )
        SELECT
            record.organization_id,
            record.id,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            'migration:20260729_994',
            'migration:20260729_994'
        FROM documents.document_records record
        ON CONFLICT (organization_id, document_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION documents.initialize_document_organization_association_aggregate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO documents.document_organization_association_aggregates (
                organization_id,
                document_id,
                revision,
                created_at,
                updated_at,
                created_by,
                updated_by
            )
            VALUES (
                NEW.organization_id,
                NEW.id,
                0,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                COALESCE(NEW.created_by, 'database:document_insert'),
                COALESCE(NEW.created_by, 'database:document_insert')
            )
            ON CONFLICT (organization_id, document_id) DO NOTHING;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_initialize_document_organization_association_aggregate
        AFTER INSERT ON documents.document_records
        FOR EACH ROW
        EXECUTE FUNCTION documents.initialize_document_organization_association_aggregate()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_initialize_document_organization_association_aggregate "
        "ON documents.document_records"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS documents.initialize_document_organization_association_aggregate()"
    )
    op.drop_index(
        "ix_document_organization_associations_node_status",
        table_name="document_organization_associations",
        schema="documents",
    )
    op.drop_index(
        "ix_document_organization_associations_document_status",
        table_name="document_organization_associations",
        schema="documents",
    )
    op.drop_table("document_organization_associations", schema="documents")
    op.drop_table(
        "document_organization_association_aggregates",
        schema="documents",
    )
    op.drop_constraint(
        "uq_organization_nodes_organization_identity",
        "organization_nodes",
        schema="core",
        type_="unique",
    )
    op.drop_constraint(
        "uq_document_records_organization_identity",
        "document_records",
        schema="documents",
        type_="unique",
    )
