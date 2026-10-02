"""align processing revision timestamp defaults

Revision ID: 20260825_2100
Revises: 20260819_1000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260825_2100"
down_revision: str | None = "20260819_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "processing_revisions",
        "created_at",
        schema="documents",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "processing_revisions",
        "updated_at",
        schema="documents",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "processing_revisions",
        "updated_at",
        schema="documents",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "processing_revisions",
        "created_at",
        schema="documents",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
