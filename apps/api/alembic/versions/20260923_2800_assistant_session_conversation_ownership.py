"""enforce assistant session conversation organization ownership

Revision ID: 20260923_2800
Revises: 20260827_2700
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_2800"
down_revision: str | Sequence[str] | None = "20260827_2700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_ORGANIZATION_UNIQUE = "uq_ai_assistant_sessions_id_organization"
CONVERSATION_SESSION_ORGANIZATION_FK = "fk_ai_conversations_session_organization"


def upgrade() -> None:
    connection = op.get_bind()
    invalid_lineage = list(
        connection.execute(
            sa.text(
                """
                SELECT conversation.conversation_id,
                       conversation.organization_id AS conversation_organization_id,
                       session.assistant_session_id,
                       session.organization_id AS session_organization_id,
                       session.ownership_scope AS session_ownership_scope
                FROM ai.conversations AS conversation
                JOIN ai.assistant_sessions AS session
                  ON session.assistant_session_id = conversation.assistant_session_id
                WHERE conversation.assistant_session_id IS NOT NULL
                  AND conversation.organization_id IS NOT NULL
                  AND (
                      session.ownership_scope <> 'organization'
                      OR session.organization_id IS DISTINCT FROM conversation.organization_id
                  )
                ORDER BY conversation.conversation_id
                """
            )
        ).mappings()
    )
    if invalid_lineage:
        summary = ", ".join(
            f"{row['conversation_id']} / {row['assistant_session_id']}" for row in invalid_lineage
        )
        raise RuntimeError(
            "Cannot enforce assistant session conversation organization ownership because invalid historical "
            "lineage exists. Resolve cross-organization, global, or legacy session attachments through a "
            f"governed process first: {summary}"
        )

    op.create_unique_constraint(
        SESSION_ORGANIZATION_UNIQUE,
        "assistant_sessions",
        ["assistant_session_id", "organization_id"],
        schema="ai",
    )
    op.create_foreign_key(
        CONVERSATION_SESSION_ORGANIZATION_FK,
        "conversations",
        "assistant_sessions",
        ["assistant_session_id", "organization_id"],
        ["assistant_session_id", "organization_id"],
        source_schema="ai",
        referent_schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint(
        CONVERSATION_SESSION_ORGANIZATION_FK,
        "conversations",
        schema="ai",
        type_="foreignkey",
    )
    op.drop_constraint(
        SESSION_ORGANIZATION_UNIQUE,
        "assistant_sessions",
        schema="ai",
        type_="unique",
    )
