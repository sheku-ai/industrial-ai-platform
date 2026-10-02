"""persist ownership across the assistant pipeline

Revision ID: 20260713_900
Revises: 20260712_890
Create Date: 2026-07-13 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260713_900"
down_revision = "20260712_890"
branch_labels = None
depends_on = None

DIRECT_ASSISTANT_TABLES = (
    "assistant_sessions",
    "assistant_runtime_runs",
    "assistant_retrieval_plans",
    "assistant_retrieval_execution_plans",
    "assistant_search_executions",
    "assistant_context_packages",
    "assistant_prompt_packages",
    "assistant_llm_invocation_plans",
    "assistant_llm_executions",
    "assistant_responses",
)
OWNED_TABLES = (*DIRECT_ASSISTANT_TABLES, "assistant_citation_verifications")


def _add_ownership(table: str) -> None:
    op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True)), schema="ai")
    op.add_column(
        table,
        sa.Column("ownership_scope", sa.String(32), server_default="legacy_unscoped", nullable=False),
        schema="ai",
    )
    op.add_column(
        table,
        sa.Column("data_origin", sa.String(32), server_default="legacy", nullable=False),
        schema="ai",
    )
    op.create_foreign_key(
        f"fk_ai_{table}_organization",
        table,
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema="ai",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    op.create_index(f"ix_ai_{table}_organization_created", table, ["organization_id", "created_at"], schema="ai")
    op.create_index(f"ix_ai_{table}_scope_created", table, ["ownership_scope", "created_at"], schema="ai")


def _invalidate(table: str, predicate: str) -> None:
    op.execute(
        f"""
        UPDATE ai.{table} item
        SET organization_id = NULL,
            ownership_scope = 'legacy_unscoped',
            data_origin = 'legacy'
        WHERE {predicate}
        """
    )


def upgrade() -> None:
    for table in OWNED_TABLES:
        _add_ownership(table)

    for table in DIRECT_ASSISTANT_TABLES:
        op.execute(
            f"""
            UPDATE ai.{table} item
            SET organization_id = assistant.organization_id,
                ownership_scope = assistant.ownership_scope,
                data_origin = assistant.data_origin
            FROM ai.assistant_definitions assistant
            WHERE item.assistant_id = assistant.assistant_id
              AND assistant.ownership_scope IN ('organization', 'global')
            """
        )

    op.execute(
        """
        UPDATE ai.assistant_citation_verifications item
        SET organization_id = execution.organization_id,
            ownership_scope = execution.ownership_scope,
            data_origin = execution.data_origin
        FROM ai.assistant_llm_executions execution
        WHERE item.llm_execution_id = execution.llm_execution_id
          AND execution.ownership_scope IN ('organization', 'global')
        """
    )

    _invalidate(
        "assistant_runtime_runs",
        "EXISTS (SELECT 1 FROM ai.assistant_sessions parent "
        "WHERE parent.assistant_session_id = item.assistant_session_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_retrieval_execution_plans",
        "EXISTS (SELECT 1 FROM ai.assistant_retrieval_plans parent "
        "WHERE parent.retrieval_plan_id = item.retrieval_plan_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_search_executions",
        "EXISTS (SELECT 1 FROM ai.assistant_retrieval_execution_plans parent "
        "WHERE parent.execution_plan_id = item.execution_plan_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_context_packages",
        "EXISTS (SELECT 1 FROM ai.assistant_search_executions parent "
        "WHERE parent.search_execution_id = item.search_execution_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_prompt_packages",
        "EXISTS (SELECT 1 FROM ai.assistant_context_packages parent "
        "WHERE parent.context_package_id = item.context_package_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_llm_invocation_plans",
        "EXISTS (SELECT 1 FROM ai.assistant_prompt_packages parent "
        "WHERE parent.prompt_package_id = item.prompt_package_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_llm_executions",
        "EXISTS (SELECT 1 FROM ai.assistant_llm_invocation_plans parent "
        "WHERE parent.gateway_id = item.gateway_id "
        "AND (parent.assistant_id <> item.assistant_id OR parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_citation_verifications",
        "EXISTS (SELECT 1 FROM ai.assistant_llm_executions parent "
        "WHERE parent.llm_execution_id = item.llm_execution_id "
        "AND (parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )
    _invalidate(
        "assistant_responses",
        "EXISTS (SELECT 1 FROM ai.assistant_citation_verifications parent "
        "WHERE parent.citation_verification_id = item.citation_verification_id "
        "AND (parent.ownership_scope <> item.ownership_scope "
        "OR parent.organization_id IS DISTINCT FROM item.organization_id))",
    )

    for table in OWNED_TABLES:
        op.create_check_constraint(
            f"ck_ai_{table}_ownership",
            table,
            "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
            "(ownership_scope IN ('global','legacy_unscoped') AND organization_id IS NULL)",
            schema="ai",
        )
        op.create_check_constraint(
            f"ck_ai_{table}_origin",
            table,
            "data_origin IN ('operational','reference','validation','legacy')",
            schema="ai",
        )


def downgrade() -> None:
    for table in reversed(OWNED_TABLES):
        op.drop_constraint(f"ck_ai_{table}_origin", table, schema="ai", type_="check")
        op.drop_constraint(f"ck_ai_{table}_ownership", table, schema="ai", type_="check")
        op.drop_index(f"ix_ai_{table}_scope_created", table_name=table, schema="ai")
        op.drop_index(f"ix_ai_{table}_organization_created", table_name=table, schema="ai")
        op.drop_constraint(f"fk_ai_{table}_organization", table, schema="ai", type_="foreignkey")
        op.drop_column(table, "data_origin", schema="ai")
        op.drop_column(table, "ownership_scope", schema="ai")
        op.drop_column(table, "organization_id", schema="ai")
