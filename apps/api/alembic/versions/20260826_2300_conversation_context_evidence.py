"""add authoritative conversation context evidence

Revision ID: 20260826_2300
Revises: 20260825_2200
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_2300"
down_revision: str | None = "20260825_2200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ai_conversation_turns_id_conversation_organization",
        "conversation_turns",
        ["conversation_turn_id", "conversation_id", "organization_id"],
        schema="ai",
    )
    op.create_table(
        "conversation_context_packages",
        sa.Column("conversation_context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="organization", nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_user_message", sa.Text(), nullable=False),
        sa.Column(
            "included_turn_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "excluded_turns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "context_window_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("context_policy_version", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "retrieval_inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_context_package_id", name="pk_ai_conversation_context_packages"),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_context_packages_organization_turn",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_conversation_context_packages_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_context_packages_scoped_turn",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_context_packages_ownership",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_context_packages_origin",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_context_packages_conversation",
        "conversation_context_packages",
        ["organization_id", "conversation_id", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_context_packages_hash",
        "conversation_context_packages",
        ["context_hash"],
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index("ix_ai_conversation_context_packages_hash", table_name="conversation_context_packages", schema="ai")
    op.drop_index(
        "ix_ai_conversation_context_packages_conversation",
        table_name="conversation_context_packages",
        schema="ai",
    )
    op.drop_table("conversation_context_packages", schema="ai")
    op.drop_constraint(
        "uq_ai_conversation_turns_id_conversation_organization",
        "conversation_turns",
        schema="ai",
        type_="unique",
    )
