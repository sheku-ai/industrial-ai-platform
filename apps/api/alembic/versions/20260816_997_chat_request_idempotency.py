"""persist chat request idempotency

Revision ID: 20260816_997
Revises: 20260814_996
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_997"
down_revision: str | Sequence[str] | None = "20260814_996"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_ai_conversation_turns_chat_request"


def upgrade() -> None:
    connection = op.get_bind()

    incompatible_request_ids = list(
        connection.execute(
            sa.text(
                """
                SELECT conversation_turn_id,
                       btrim(turn_metadata->>'idempotency_key') AS request_id
                FROM ai.conversation_turns
                WHERE turn_role = 'user'
                  AND NULLIF(btrim(turn_metadata->>'idempotency_key'), '') IS NOT NULL
                  AND length(btrim(turn_metadata->>'idempotency_key')) > 128
                ORDER BY conversation_turn_id
                """
            )
        ).mappings()
    )
    if incompatible_request_ids:
        summary = ", ".join(
            f"{row['conversation_turn_id']} ({len(row['request_id'])} chars)"
            for row in incompatible_request_ids
        )
        raise RuntimeError(
            "Cannot persist chat request idempotency because historical request identifiers exceed 128 characters. "
            "Resolve incompatible conversation turns through a governed process first: "
            f"{summary}"
        )

    op.add_column(
        "conversation_turns",
        sa.Column("request_id", sa.String(length=128), nullable=True),
        schema="ai",
    )

    connection.execute(
        sa.text(
            """
            UPDATE ai.conversation_turns
            SET request_id = btrim(turn_metadata->>'idempotency_key')
            WHERE turn_role = 'user'
              AND NULLIF(btrim(turn_metadata->>'idempotency_key'), '') IS NOT NULL
            """
        )
    )

    duplicate_requests = list(
        connection.execute(
            sa.text(
                """
                SELECT organization_id,
                       assistant_id,
                       request_id,
                       count(*) AS turn_count
                FROM ai.conversation_turns
                WHERE request_id IS NOT NULL
                  AND turn_role = 'user'
                GROUP BY organization_id, assistant_id, request_id
                HAVING count(*) > 1
                ORDER BY organization_id, assistant_id, request_id
                """
            )
        ).mappings()
    )
    if duplicate_requests:
        summary = ", ".join(
            f"{row['organization_id']} / {row['assistant_id']} / {row['request_id']} ({row['turn_count']})"
            for row in duplicate_requests
        )
        raise RuntimeError(
            "Cannot enforce chat request idempotency because duplicate request identifiers exist. "
            "Resolve duplicated chat requests through a governed process first: "
            f"{summary}"
        )

    op.create_index(
        INDEX_NAME,
        "conversation_turns",
        ["organization_id", "assistant_id", "request_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("request_id IS NOT NULL AND turn_role = 'user'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="conversation_turns", schema="ai")
    op.drop_column("conversation_turns", "request_id", schema="ai")
