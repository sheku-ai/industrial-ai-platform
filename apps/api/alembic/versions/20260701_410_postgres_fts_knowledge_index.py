"""postgres fts knowledge index

Revision ID: 20260701_410
Revises: 20260701_400
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_410"
down_revision = "20260701_400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True),
            nullable=True,
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_chunks_search_vector",
        "chunks",
        ["search_vector"],
        schema="knowledge",
        postgresql_using="gin",
    )
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runtime_persistence_records_domain", "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        "ck_runtime_persistence_records_domain",
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','enterprise_search','runtime_persistence')",
        schema="runtime",
    )
    op.drop_index("ix_knowledge_chunks_search_vector", table_name="chunks", schema="knowledge")
    op.drop_column("chunks", "search_vector", schema="knowledge")
