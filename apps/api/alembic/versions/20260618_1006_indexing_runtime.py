"""indexing execution runtime

Revision ID: 20260618_1006
Revises: 0001_platform_foundation
Create Date: 2026-06-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260618_1006"
down_revision: Union[str, None] = "0001_platform_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('documents.indexing_jobs') IS NOT NULL THEN
                ALTER TABLE documents.indexing_jobs
                    ALTER COLUMN collection_id DROP NOT NULL;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('documents.indexing_jobs') IS NOT NULL THEN
                ALTER TABLE documents.indexing_jobs
                    ALTER COLUMN collection_id SET NOT NULL;
            END IF;
        END
        $$;
        """
    )
