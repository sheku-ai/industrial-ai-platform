"""enforce assistant response idempotency

Revision ID: 20260814_996
Revises: 20260807_995
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_996"
down_revision: str | Sequence[str] | None = "20260807_995"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "uq_ai_assistant_responses_citation_verification"


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_verifications = list(
        connection.execute(
            sa.text(
                """
                SELECT citation_verification_id, count(*) AS response_count
                FROM ai.assistant_responses
                GROUP BY citation_verification_id
                HAVING count(*) > 1
                ORDER BY citation_verification_id
                """
            )
        ).mappings()
    )
    if duplicate_verifications:
        summary = ", ".join(
            f"{row['citation_verification_id']} ({row['response_count']})"
            for row in duplicate_verifications
        )
        raise RuntimeError(
            "Cannot enforce assistant response idempotency. "
            "Resolve duplicated citation verification responses through a governed process first: "
            f"{summary}"
        )

    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "assistant_responses",
        ["citation_verification_id"],
        schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "assistant_responses",
        schema="ai",
        type_="unique",
    )
