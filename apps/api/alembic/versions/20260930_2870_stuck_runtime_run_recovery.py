"""Persist fenced RuntimeRun claims and one provider claim per run.

Revision ID: 20260930_2870
Revises: 20260930_2860
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260930_2870"
down_revision: str | Sequence[str] | None = "20260930_2860"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT request_payload_metadata->>'assistant_run_id' AS run_id "
                "FROM ai.assistant_llm_executions "
                "WHERE request_payload_metadata ? 'assistant_run_id' "
                "GROUP BY request_payload_metadata->>'assistant_run_id' "
                "HAVING count(*) > 1 LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if duplicate is not None:
        raise RuntimeError(f"RuntimeRun {duplicate} has multiple historical provider claims")
    op.add_column("assistant_runtime_runs", sa.Column("recovery_state", sa.String(32)), schema="ai")
    op.add_column(
        "assistant_runtime_runs",
        sa.Column("recovery_owner", postgresql.UUID(as_uuid=True)),
        schema="ai",
    )
    op.add_column(
        "assistant_runtime_runs",
        sa.Column("recovery_lease_expires_at", sa.DateTime(timezone=True)),
        schema="ai",
    )
    op.add_column("assistant_runtime_runs", sa.Column("recovery_generation", sa.Integer()), schema="ai")
    op.create_check_constraint(
        "ck_ai_assistant_runtime_runs_recovery_claim",
        "assistant_runtime_runs",
        "(recovery_state IS NULL AND recovery_owner IS NULL AND recovery_lease_expires_at IS NULL "
        "AND recovery_generation IS NULL) OR "
        "(recovery_state = 'claimed' AND recovery_owner IS NOT NULL "
        "AND recovery_lease_expires_at IS NOT NULL AND recovery_generation > 0) OR "
        "(recovery_state IN ('uncertain','completed','failed','blocked') "
        "AND recovery_owner IS NULL AND recovery_lease_expires_at IS NULL AND recovery_generation > 0)",
        schema="ai",
    )
    op.create_index(
        "ix_ai_assistant_runtime_runs_recovery_lease",
        "assistant_runtime_runs",
        ["recovery_state", "recovery_lease_expires_at"],
        schema="ai",
    )
    op.create_index(
        "uq_ai_assistant_llm_executions_runtime_claim",
        "assistant_llm_executions",
        [sa.text("(request_payload_metadata ->> 'assistant_run_id')")],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("request_payload_metadata ? 'assistant_run_id'"),
    )


def downgrade() -> None:
    active = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT assistant_run_id FROM ai.assistant_runtime_runs "
                "WHERE recovery_state='claimed' ORDER BY assistant_run_id LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if active is not None:
        raise RuntimeError(f"Cannot remove recovery claims while RuntimeRun {active} is claimed")
    op.drop_index(
        "uq_ai_assistant_llm_executions_runtime_claim",
        table_name="assistant_llm_executions",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_assistant_runtime_runs_recovery_lease",
        table_name="assistant_runtime_runs",
        schema="ai",
    )
    op.drop_constraint(
        "ck_ai_assistant_runtime_runs_recovery_claim",
        "assistant_runtime_runs",
        schema="ai",
    )
    for column in (
        "recovery_generation",
        "recovery_lease_expires_at",
        "recovery_owner",
        "recovery_state",
    ):
        op.drop_column("assistant_runtime_runs", column, schema="ai")
