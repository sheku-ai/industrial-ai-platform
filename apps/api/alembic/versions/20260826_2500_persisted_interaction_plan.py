"""add persisted conversation interaction plans

Revision ID: 20260826_2500
Revises: 20260826_2400
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_2500"
down_revision: str | None = "20260826_2400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ai_conversation_interaction_decisions_id_organization_turn",
        "conversation_interaction_decisions",
        ["interaction_decision_id", "organization_id", "conversation_turn_id"],
        schema="ai",
    )
    op.create_table(
        "conversation_interaction_plans",
        sa.Column("interaction_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="organization", nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("planned_action", sa.String(length=128), nullable=False),
        sa.Column("target_runtime", sa.String(length=128), nullable=False),
        sa.Column("context_required", sa.Boolean(), nullable=False),
        sa.Column("retrieval_required", sa.Boolean(), nullable=False),
        sa.Column("generation_required", sa.Boolean(), nullable=False),
        sa.Column("use_persisted_citations", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("use_conversation_evidence", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("use_conversation_context", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enterprise_search_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deterministic_response_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("planner_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "plan_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("interaction_plan_id", name="pk_ai_conversation_interaction_plans"),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_interaction_plans_org_turn",
        ),
        sa.UniqueConstraint(
            "interaction_plan_id",
            "organization_id",
            name="uq_ai_conversation_interaction_plans_id_organization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_conversation_interaction_plans_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["ai.conversations.conversation_id", "ai.conversations.organization_id"],
            name="fk_ai_conversation_interaction_plans_scoped_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_turn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_context",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interaction_decision_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_interaction_decisions.interaction_decision_id",
                "ai.conversation_interaction_decisions.organization_id",
                "ai.conversation_interaction_decisions.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_plans_scoped_decision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_interaction_plans_ownership",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_interaction_plans_origin",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_plans_conversation",
        "conversation_interaction_plans",
        ["organization_id", "conversation_id", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_plans_decision",
        "conversation_interaction_plans",
        ["organization_id", "interaction_decision_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_plans_input_hash",
        "conversation_interaction_plans",
        ["input_hash"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_plans_plan_hash",
        "conversation_interaction_plans",
        ["plan_hash"],
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_conversation_interaction_plans_plan_hash",
        table_name="conversation_interaction_plans",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_plans_input_hash",
        table_name="conversation_interaction_plans",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_plans_decision",
        table_name="conversation_interaction_plans",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_plans_conversation",
        table_name="conversation_interaction_plans",
        schema="ai",
    )
    op.drop_table("conversation_interaction_plans", schema="ai")
    op.drop_constraint(
        "uq_ai_conversation_interaction_decisions_id_organization_turn",
        "conversation_interaction_decisions",
        schema="ai",
        type_="unique",
    )
