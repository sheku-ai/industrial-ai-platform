"""Persist one authoritative deterministic assistant turn per interaction plan.

Revision ID: 20260930_2860
Revises: 20260930_2850
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260930_2860"
down_revision: str | Sequence[str] | None = "20260930_2850"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    contradictory = bind.execute(
        sa.text(
            "SELECT p.interaction_plan_id FROM ai.conversation_interaction_plans p "
            "JOIN ai.conversation_turns t ON t.conversation_turn_id = p.conversation_turn_id "
            "WHERE p.organization_id IS DISTINCT FROM t.organization_id "
            "OR p.conversation_id IS DISTINCT FROM t.conversation_id "
            "OR t.turn_role <> 'user' LIMIT 1"
        )
    ).scalar_one_or_none()
    if contradictory is not None:
        raise RuntimeError(f"Interaction plan {contradictory} has incompatible historical user turn lineage")
    duplicate = bind.execute(
        sa.text(
            "SELECT turn_metadata->>'interaction_plan_id' AS plan_id "
            "FROM ai.conversation_turns WHERE turn_role = 'assistant' "
            "AND assistant_response_id IS NULL AND turn_metadata ? 'interaction_plan_id' "
            "AND (turn_metadata ? 'conversation_no_search_runtime' "
            "OR turn_metadata ? 'no_evidence_response') "
            "GROUP BY turn_metadata->>'interaction_plan_id' HAVING count(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise RuntimeError(f"Deterministic interaction plan {duplicate} has duplicate historical turns")

    op.create_unique_constraint(
        "uq_ai_conversation_interaction_plans_id_org_conversation",
        "conversation_interaction_plans",
        ["interaction_plan_id", "organization_id", "conversation_id"],
        schema="ai",
    )
    op.add_column(
        "conversation_turns",
        sa.Column("deterministic_interaction_plan_id", postgresql.UUID(as_uuid=True)),
        schema="ai",
    )
    op.add_column(
        "conversation_turns",
        sa.Column("deterministic_input_fingerprint", sa.String(length=64)),
        schema="ai",
    )
    op.create_foreign_key(
        "fk_ai_conversation_turns_deterministic_plan_lineage",
        "conversation_turns",
        "conversation_interaction_plans",
        ["deterministic_interaction_plan_id", "organization_id", "conversation_id"],
        ["interaction_plan_id", "organization_id", "conversation_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_ai_conversation_turns_deterministic_identity",
        "conversation_turns",
        "(deterministic_interaction_plan_id IS NULL AND deterministic_input_fingerprint IS NULL) OR "
        "(deterministic_interaction_plan_id IS NOT NULL AND deterministic_input_fingerprint IS NOT NULL "
        "AND turn_role = 'assistant' AND assistant_response_id IS NULL AND organization_id IS NOT NULL)",
        schema="ai",
    )
    op.create_index(
        "uq_ai_conversation_turns_deterministic_operation",
        "conversation_turns",
        ["deterministic_interaction_plan_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("deterministic_interaction_plan_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_conversation_turns_deterministic_operation", table_name="conversation_turns", schema="ai")
    op.drop_constraint("ck_ai_conversation_turns_deterministic_identity", "conversation_turns", schema="ai")
    op.drop_constraint(
        "fk_ai_conversation_turns_deterministic_plan_lineage", "conversation_turns", schema="ai", type_="foreignkey"
    )
    op.drop_column("conversation_turns", "deterministic_input_fingerprint", schema="ai")
    op.drop_column("conversation_turns", "deterministic_interaction_plan_id", schema="ai")
    op.drop_constraint(
        "uq_ai_conversation_interaction_plans_id_org_conversation",
        "conversation_interaction_plans",
        schema="ai",
        type_="unique",
    )
