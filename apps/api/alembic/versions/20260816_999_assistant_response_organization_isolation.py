"""enforce assistant response organization isolation

Revision ID: 20260816_999
Revises: 20260816_998
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_999"
down_revision: str | Sequence[str] | None = "20260816_998"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESPONSE_ORGANIZATION_UNIQUE = "uq_ai_assistant_responses_id_organization"
TURN_RESPONSE_ORGANIZATION_FK = "fk_ai_conversation_turns_response_organization"


def upgrade() -> None:
    connection = op.get_bind()

    invalid_attachments = list(
        connection.execute(
            sa.text(
                """
                SELECT turn.conversation_turn_id,
                       turn.organization_id AS turn_organization_id,
                       response.assistant_response_id,
                       response.organization_id AS response_organization_id,
                       response.ownership_scope AS response_ownership_scope
                FROM ai.conversation_turns AS turn
                JOIN ai.assistant_responses AS response
                  ON response.assistant_response_id = turn.assistant_response_id
                WHERE turn.assistant_response_id IS NOT NULL
                  AND (
                      turn.organization_id IS NULL
                      OR response.ownership_scope <> 'organization'
                      OR response.organization_id IS DISTINCT FROM turn.organization_id
                  )
                ORDER BY turn.conversation_turn_id
                """
            )
        ).mappings()
    )
    if invalid_attachments:
        summary = ", ".join(
            f"{row['conversation_turn_id']} / {row['assistant_response_id']}"
            for row in invalid_attachments
        )
        raise RuntimeError(
            "Cannot enforce assistant response organization isolation because invalid historical attachments exist. "
            "Resolve cross-organization, global, or legacy response attachments through a governed process first: "
            f"{summary}"
        )

    op.create_unique_constraint(
        RESPONSE_ORGANIZATION_UNIQUE,
        "assistant_responses",
        ["assistant_response_id", "organization_id"],
        schema="ai",
    )
    op.create_foreign_key(
        TURN_RESPONSE_ORGANIZATION_FK,
        "conversation_turns",
        "assistant_responses",
        ["assistant_response_id", "organization_id"],
        ["assistant_response_id", "organization_id"],
        source_schema="ai",
        referent_schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint(
        TURN_RESPONSE_ORGANIZATION_FK,
        "conversation_turns",
        schema="ai",
        type_="foreignkey",
    )
    op.drop_constraint(
        RESPONSE_ORGANIZATION_UNIQUE,
        "assistant_responses",
        schema="ai",
        type_="unique",
    )
