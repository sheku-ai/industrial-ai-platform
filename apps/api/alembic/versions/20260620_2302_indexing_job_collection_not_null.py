"""preserve optional indexing job collection scope

Revision ID: 20260620_2302
Revises: 20260620_2301
Create Date: 2026-06-20
"""

from collections.abc import Sequence


revision: str = "20260620_2302"
down_revision: str | None = "20260620_2301"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op compatibility revision.

    Existing indexing jobs may be document-scoped, ingestion-scoped or otherwise
    valid without a collection. The SQLAlchemy model now preserves the existing
    nullable database contract instead of forcing a destructive or fabricated
    collection assignment.
    """


def downgrade() -> None:
    """No-op: this revision does not alter persistent data or schema."""
