"""enforce assistant pipeline session and organization lineage

Revision ID: 20260923_2810
Revises: 20260923_2800
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_2810"
down_revision: str | Sequence[str] | None = "20260923_2800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIQUE_CONSTRAINTS = (
    ("assistant_sessions", "uq_ai_assistant_sessions_id_assistant_organization",
     ["assistant_session_id", "assistant_id", "organization_id"]),
    ("assistant_retrieval_plans", "uq_ai_assistant_retrieval_plans_lineage",
     ["retrieval_plan_id", "assistant_id", "organization_id"]),
    ("assistant_retrieval_execution_plans", "uq_ai_assistant_retrieval_execution_plans_lineage",
     ["execution_plan_id", "retrieval_plan_id", "assistant_id", "organization_id"]),
)

FOREIGN_KEYS = (
    ("assistant_runtime_runs", "assistant_sessions", "fk_ai_assistant_runtime_runs_scoped_session",
     ["assistant_session_id", "assistant_id", "organization_id"],
     ["assistant_session_id", "assistant_id", "organization_id"]),
    ("assistant_retrieval_plans", "assistant_sessions", "fk_ai_assistant_retrieval_plans_scoped_session",
     ["assistant_session_id", "assistant_id", "organization_id"],
     ["assistant_session_id", "assistant_id", "organization_id"]),
    ("assistant_retrieval_execution_plans", "assistant_retrieval_plans",
     "fk_ai_assistant_retrieval_execution_plans_scoped_plan",
     ["retrieval_plan_id", "assistant_id", "organization_id"],
     ["retrieval_plan_id", "assistant_id", "organization_id"]),
    ("assistant_search_executions", "assistant_retrieval_execution_plans",
     "fk_ai_assistant_search_executions_scoped_execution",
     ["execution_plan_id", "retrieval_plan_id", "assistant_id", "organization_id"],
     ["execution_plan_id", "retrieval_plan_id", "assistant_id", "organization_id"]),
)

HISTORICAL_CHECKS = (
    ("assistant_runtime_runs", "run.assistant_run_id", """
        SELECT run.assistant_run_id AS invalid_id
        FROM ai.assistant_runtime_runs AS run
        LEFT JOIN ai.assistant_sessions AS session
          ON session.assistant_session_id = run.assistant_session_id
        WHERE session.assistant_session_id IS NULL
           OR run.assistant_id IS DISTINCT FROM session.assistant_id
           OR run.organization_id IS DISTINCT FROM session.organization_id
           OR run.ownership_scope IS DISTINCT FROM session.ownership_scope
        LIMIT 1
    """),
    ("assistant_retrieval_plans", "plan.retrieval_plan_id", """
        SELECT plan.retrieval_plan_id AS invalid_id
        FROM ai.assistant_retrieval_plans AS plan
        LEFT JOIN ai.assistant_sessions AS session
          ON session.assistant_session_id = plan.assistant_session_id
        WHERE plan.assistant_session_id IS NOT NULL
          AND (session.assistant_session_id IS NULL
               OR plan.assistant_id IS DISTINCT FROM session.assistant_id
               OR plan.organization_id IS DISTINCT FROM session.organization_id
               OR plan.ownership_scope IS DISTINCT FROM session.ownership_scope)
        LIMIT 1
    """),
    ("assistant_retrieval_execution_plans", "execution.execution_plan_id", """
        SELECT execution.execution_plan_id AS invalid_id
        FROM ai.assistant_retrieval_execution_plans AS execution
        LEFT JOIN ai.assistant_retrieval_plans AS plan
          ON plan.retrieval_plan_id = execution.retrieval_plan_id
        WHERE plan.retrieval_plan_id IS NULL
           OR execution.assistant_id IS DISTINCT FROM plan.assistant_id
           OR execution.assistant_session_id IS DISTINCT FROM plan.assistant_session_id
           OR execution.organization_id IS DISTINCT FROM plan.organization_id
           OR execution.ownership_scope IS DISTINCT FROM plan.ownership_scope
        LIMIT 1
    """),
    ("assistant_search_executions", "search.search_execution_id", """
        SELECT search.search_execution_id AS invalid_id
        FROM ai.assistant_search_executions AS search
        LEFT JOIN ai.assistant_retrieval_execution_plans AS execution
          ON execution.execution_plan_id = search.execution_plan_id
        LEFT JOIN ai.assistant_retrieval_plans AS plan
          ON plan.retrieval_plan_id = search.retrieval_plan_id
        WHERE execution.execution_plan_id IS NULL OR plan.retrieval_plan_id IS NULL
           OR search.retrieval_plan_id IS DISTINCT FROM execution.retrieval_plan_id
           OR search.assistant_id IS DISTINCT FROM execution.assistant_id
           OR search.assistant_session_id IS DISTINCT FROM execution.assistant_session_id
           OR search.organization_id IS DISTINCT FROM execution.organization_id
           OR search.ownership_scope IS DISTINCT FROM execution.ownership_scope
           OR execution.assistant_id IS DISTINCT FROM plan.assistant_id
           OR execution.assistant_session_id IS DISTINCT FROM plan.assistant_session_id
           OR execution.organization_id IS DISTINCT FROM plan.organization_id
           OR execution.ownership_scope IS DISTINCT FROM plan.ownership_scope
        LIMIT 1
    """),
)

CHILD_TABLES = (
    "assistant_runtime_runs",
    "assistant_retrieval_plans",
    "assistant_retrieval_execution_plans",
    "assistant_search_executions",
)
PARENT_TABLES = ("assistant_sessions", "assistant_retrieval_plans", "assistant_retrieval_execution_plans")


def upgrade() -> None:
    connection = op.get_bind()
    for table, _identifier, query in HISTORICAL_CHECKS:
        invalid_id = connection.execute(sa.text(query)).scalar_one_or_none()
        if invalid_id is not None:
            raise RuntimeError(
                f"Cannot enforce assistant pipeline lineage: {table} contains incompatible historical row "
                f"{invalid_id}. Resolve it through a governed process before upgrading."
            )

    for table, name, columns in UNIQUE_CONSTRAINTS:
        op.create_unique_constraint(name, table, columns, schema="ai")
    for source, target, name, local_columns, remote_columns in FOREIGN_KEYS:
        op.create_foreign_key(
            name, source, target, local_columns, remote_columns,
            source_schema="ai", referent_schema="ai",
        )

    op.execute("""
        CREATE FUNCTION ai.enforce_assistant_pipeline_lineage() RETURNS trigger
        LANGUAGE plpgsql AS $function$
        BEGIN
          IF TG_NAME = 'ck_ai_assistant_runtime_runs_lineage' THEN
            IF NOT EXISTS (
              SELECT 1 FROM ai.assistant_sessions AS parent
              WHERE parent.assistant_session_id = NEW.assistant_session_id
                AND parent.assistant_id = NEW.assistant_id
                AND parent.organization_id IS NOT DISTINCT FROM NEW.organization_id
                AND parent.ownership_scope = NEW.ownership_scope
            ) THEN RAISE EXCEPTION 'assistant runtime run session lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_retrieval_plans_lineage' THEN
            IF NEW.assistant_session_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM ai.assistant_sessions AS parent
              WHERE parent.assistant_session_id = NEW.assistant_session_id
                AND parent.assistant_id = NEW.assistant_id
                AND parent.organization_id IS NOT DISTINCT FROM NEW.organization_id
                AND parent.ownership_scope = NEW.ownership_scope
            ) THEN RAISE EXCEPTION 'assistant retrieval plan session lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_retrieval_execution_plans_lineage' THEN
            IF NOT EXISTS (
              SELECT 1 FROM ai.assistant_retrieval_plans AS parent
              WHERE parent.retrieval_plan_id = NEW.retrieval_plan_id
                AND parent.assistant_id = NEW.assistant_id
                AND parent.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
                AND parent.organization_id IS NOT DISTINCT FROM NEW.organization_id
                AND parent.ownership_scope = NEW.ownership_scope
            ) THEN RAISE EXCEPTION 'assistant retrieval execution lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_search_executions_lineage' THEN
            IF NOT EXISTS (
              SELECT 1 FROM ai.assistant_retrieval_execution_plans AS parent
              WHERE parent.execution_plan_id = NEW.execution_plan_id
                AND parent.retrieval_plan_id = NEW.retrieval_plan_id
                AND parent.assistant_id = NEW.assistant_id
                AND parent.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
                AND parent.organization_id IS NOT DISTINCT FROM NEW.organization_id
                AND parent.ownership_scope = NEW.ownership_scope
            ) THEN RAISE EXCEPTION 'assistant search execution lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_sessions_child_lineage' THEN
            IF EXISTS (
              SELECT 1 FROM ai.assistant_runtime_runs AS child
              WHERE child.assistant_session_id = NEW.assistant_session_id
                AND (child.assistant_id IS DISTINCT FROM NEW.assistant_id
                  OR child.organization_id IS DISTINCT FROM NEW.organization_id
                  OR child.ownership_scope IS DISTINCT FROM NEW.ownership_scope)
            ) OR EXISTS (
              SELECT 1 FROM ai.assistant_retrieval_plans AS child
              WHERE child.assistant_session_id = NEW.assistant_session_id
                AND (child.assistant_id IS DISTINCT FROM NEW.assistant_id
                  OR child.organization_id IS DISTINCT FROM NEW.organization_id
                  OR child.ownership_scope IS DISTINCT FROM NEW.ownership_scope)
            ) THEN RAISE EXCEPTION 'assistant session child lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_retrieval_plans_child_lineage' THEN
            IF EXISTS (
              SELECT 1 FROM ai.assistant_retrieval_execution_plans AS child
              WHERE child.retrieval_plan_id = NEW.retrieval_plan_id
                AND (child.assistant_id IS DISTINCT FROM NEW.assistant_id
                  OR child.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id
                  OR child.organization_id IS DISTINCT FROM NEW.organization_id
                  OR child.ownership_scope IS DISTINCT FROM NEW.ownership_scope)
            ) THEN RAISE EXCEPTION 'retrieval plan child lineage mismatch'; END IF;
          ELSIF TG_NAME = 'ck_ai_assistant_retrieval_execution_plans_child_lineage' THEN
            IF EXISTS (
              SELECT 1 FROM ai.assistant_search_executions AS child
              WHERE child.execution_plan_id = NEW.execution_plan_id
                AND (child.retrieval_plan_id IS DISTINCT FROM NEW.retrieval_plan_id
                  OR child.assistant_id IS DISTINCT FROM NEW.assistant_id
                  OR child.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id
                  OR child.organization_id IS DISTINCT FROM NEW.organization_id
                  OR child.ownership_scope IS DISTINCT FROM NEW.ownership_scope)
            ) THEN RAISE EXCEPTION 'retrieval execution child lineage mismatch'; END IF;
          END IF;
          RETURN NEW;
        END;
        $function$
    """)
    for table in CHILD_TABLES:
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER ck_ai_{table}_lineage
            AFTER INSERT OR UPDATE ON ai.{table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION ai.enforce_assistant_pipeline_lineage()
        """)
    for table in PARENT_TABLES:
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER ck_ai_{table}_child_lineage
            AFTER UPDATE ON ai.{table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION ai.enforce_assistant_pipeline_lineage()
        """)


def downgrade() -> None:
    for table in reversed(PARENT_TABLES):
        op.execute(f"DROP TRIGGER ck_ai_{table}_child_lineage ON ai.{table}")
    for table in reversed(CHILD_TABLES):
        op.execute(f"DROP TRIGGER ck_ai_{table}_lineage ON ai.{table}")
    op.execute("DROP FUNCTION ai.enforce_assistant_pipeline_lineage()")
    for source, _target, name, _local, _remote in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, source, schema="ai", type_="foreignkey")
    for table, name, _columns in reversed(UNIQUE_CONSTRAINTS):
        op.drop_constraint(name, table, schema="ai", type_="unique")
