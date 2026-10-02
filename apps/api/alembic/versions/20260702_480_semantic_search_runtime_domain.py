"""add semantic search runtime persistence domain

Revision ID: 20260702_480
Revises: 20260702_460
Create Date: 2026-07-02
"""

from alembic import op


revision = "20260702_480"
down_revision = "20260702_460"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_runtime_persistence_records_domain"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','semantic_search_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "persistence_records", schema="runtime", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "persistence_records",
        "runtime_domain IN ('storage','processing','chunk','knowledge_publication','knowledge_index','knowledge_lifecycle','knowledge_fts','embedding_runtime','vector_index_runtime','enterprise_search','runtime_persistence')",
        schema="runtime",
    )