"""runtime persistence records

Revision ID: 20260701_360
Revises: 20260625_272a
Create Date: 2026-07-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260701_360"
down_revision: Union[str, None] = "20260625_272a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS runtime")
    op.create_table(
        "persistence_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("runtime_domain", sa.String(64), nullable=False),
        sa.Column("record_type", sa.String(128), nullable=False),
        sa.Column("record_key", sa.String(512), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=True),
        sa.Column("processing_session_id", sa.String(255), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        sa.Column("provider", sa.String(128), nullable=True),
        sa.Column("execution_status", sa.String(64), nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("summary", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("validation", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metrics", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("persistence_status", sa.String(32), server_default="persisted", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_persistence_records"),
        sa.UniqueConstraint("execution_id", "runtime_domain", "record_type", "record_key", name="uq_runtime_persistence_record_identity"),
        sa.CheckConstraint(
            "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','enterprise_search','runtime_persistence')",
            name="ck_runtime_persistence_records_domain",
        ),
        sa.CheckConstraint("persistence_status IN ('persisted','failed','skipped')", name="ck_runtime_persistence_records_status"),
        schema="runtime",
    )
    op.create_index("ix_runtime_persistence_execution", "persistence_records", ["execution_id"], schema="runtime")
    op.create_index("ix_runtime_persistence_domain_status", "persistence_records", ["runtime_domain", "persistence_status"], schema="runtime")
    op.create_index("ix_runtime_persistence_artifact", "persistence_records", ["artifact_id"], schema="runtime")
    op.create_index("ix_runtime_persistence_correlation", "persistence_records", ["correlation_id"], schema="runtime")


def downgrade() -> None:
    op.drop_index("ix_runtime_persistence_correlation", table_name="persistence_records", schema="runtime")
    op.drop_index("ix_runtime_persistence_artifact", table_name="persistence_records", schema="runtime")
    op.drop_index("ix_runtime_persistence_domain_status", table_name="persistence_records", schema="runtime")
    op.drop_index("ix_runtime_persistence_execution", table_name="persistence_records", schema="runtime")
    op.drop_table("persistence_records", schema="runtime")
