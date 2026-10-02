"""Persist one authoritative provider claim per LLM invocation plan.

Revision ID: 20260930_2850
Revises: 20260924_2840
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260930_2850"
down_revision: str | Sequence[str] | None = "20260924_2840"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "assistant_llm_executions"
CLAIM_INDEX = "uq_ai_assistant_llm_executions_gateway_claim"
STATUS_CHECK = "ck_ai_assistant_llm_executions_status"


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT gateway_id, count(*) AS row_count FROM ai.assistant_llm_executions "
                "GROUP BY gateway_id HAVING count(*) > 1 ORDER BY gateway_id LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot enforce provider claim: plan {duplicate['gateway_id']} has "
            f"{duplicate['row_count']} historical executions; review attempts before upgrading."
        )
    op.add_column(TABLE, sa.Column("provider_call_started_at", sa.DateTime(timezone=True)), schema="ai")
    op.add_column(TABLE, sa.Column("provider_call_finished_at", sa.DateTime(timezone=True)), schema="ai")
    op.drop_constraint(STATUS_CHECK, TABLE, schema="ai", type_="check")
    op.create_check_constraint(
        STATUS_CHECK,
        TABLE,
        "execution_status IN ('prepared','running','completed','blocked','failed','disabled')",
        schema="ai",
    )
    op.create_index(CLAIM_INDEX, TABLE, ["gateway_id"], unique=True, schema="ai")


def downgrade() -> None:
    running = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT llm_execution_id FROM ai.assistant_llm_executions "
                "WHERE execution_status = 'running' ORDER BY llm_execution_id LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if running is not None:
        raise RuntimeError(f"Cannot remove provider claim lifecycle while execution {running} is running.")
    op.drop_index(CLAIM_INDEX, table_name=TABLE, schema="ai")
    op.drop_constraint(STATUS_CHECK, TABLE, schema="ai", type_="check")
    op.create_check_constraint(
        STATUS_CHECK,
        TABLE,
        "execution_status IN ('prepared','completed','blocked','failed','disabled')",
        schema="ai",
    )
    op.drop_column(TABLE, "provider_call_finished_at", schema="ai")
    op.drop_column(TABLE, "provider_call_started_at", schema="ai")
