"""enforce assistant response attachment idempotency

Revision ID: 20260816_998
Revises: 20260816_997
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_998"
down_revision: str | Sequence[str] | None = "20260816_997"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_ai_conversation_turns_assistant_response"


def upgrade() -> None:
    connection = op.get_bind()

    duplicate_attachments = list(
        connection.execute(
            sa.text(
                """
                SELECT conversation_id,
                       assistant_response_id,
                       count(*) AS turn_count
                FROM ai.conversation_turns
                WHERE assistant_response_id IS NOT NULL
                GROUP BY conversation_id, assistant_response_id
                HAVING count(*) > 1
                ORDER BY conversation_id, assistant_response_id
                """
            )
        ).mappings()
    )
    if duplicate_attachments:
        summary = ", ".join(
            f"{row['conversation_id']} / {row['assistant_response_id']} ({row['turn_count']})"
            for row in duplicate_attachments
        )
        raise RuntimeError(
            "Cannot enforce assistant response attachment idempotency because duplicate attachments exist. "
            "Resolve duplicated conversation response attachments through a governed process first: "
            f"{summary}"
        )

    op.create_index(
        INDEX_NAME,
        "conversation_turns",
        ["conversation_id", "assistant_response_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("assistant_response_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="conversation_turns", schema="ai")
