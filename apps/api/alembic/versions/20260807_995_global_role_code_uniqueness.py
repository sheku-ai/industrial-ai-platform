"""enforce unique global security role codes

Revision ID: 20260807_995
Revises: 20260729_994
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_995"
down_revision: str | Sequence[str] | None = "20260729_994"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GLOBAL_ROLE_CODE_INDEX = "uq_security_roles_global_code"


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_codes = list(
        connection.execute(
            sa.text(
                """
                SELECT code, count(*) AS role_count
                FROM security.roles
                WHERE organization_id IS NULL
                GROUP BY code
                HAVING count(*) > 1
                ORDER BY code
                """
            )
        ).mappings()
    )
    if duplicate_codes:
        summary = ", ".join(
            f"{row['code']} ({row['role_count']})"
            for row in duplicate_codes
        )
        raise RuntimeError(
            "Cannot enforce unique global security role codes. "
            f"Resolve the duplicated global role codes through a governed process first: {summary}"
        )

    op.create_index(
        GLOBAL_ROLE_CODE_INDEX,
        "roles",
        ["code"],
        unique=True,
        schema="security",
        postgresql_where=sa.text("organization_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(GLOBAL_ROLE_CODE_INDEX, table_name="roles", schema="security")
