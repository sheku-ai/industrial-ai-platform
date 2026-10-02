# ruff: noqa: E501
"""assistant downstream authoritative lineage

Revision ID: 20260923_2820
Revises: 20260923_2810
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_2820"
down_revision: str | Sequence[str] | None = "20260923_2810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = (
    (
        "assistant_context_packages",
        """SELECT c.context_package_id FROM ai.assistant_context_packages c LEFT JOIN ai.assistant_search_executions s ON s.search_execution_id=c.search_execution_id WHERE s.search_execution_id IS NULL OR c.assistant_id IS DISTINCT FROM s.assistant_id OR c.assistant_session_id IS DISTINCT FROM s.assistant_session_id OR c.organization_id IS DISTINCT FROM s.organization_id OR c.ownership_scope IS DISTINCT FROM s.ownership_scope LIMIT 1""",
    ),
    (
        "assistant_prompt_packages",
        """SELECT p.prompt_package_id FROM ai.assistant_prompt_packages p LEFT JOIN ai.assistant_context_packages c ON c.context_package_id=p.context_package_id WHERE c.context_package_id IS NULL OR p.assistant_id IS DISTINCT FROM c.assistant_id OR p.assistant_session_id IS DISTINCT FROM c.assistant_session_id OR p.organization_id IS DISTINCT FROM c.organization_id OR p.ownership_scope IS DISTINCT FROM c.ownership_scope LIMIT 1""",
    ),
    (
        "assistant_llm_invocation_plans",
        """SELECT g.gateway_id FROM ai.assistant_llm_invocation_plans g LEFT JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=g.prompt_package_id WHERE p.prompt_package_id IS NULL OR g.assistant_id IS DISTINCT FROM p.assistant_id OR g.assistant_session_id IS DISTINCT FROM p.assistant_session_id OR g.organization_id IS DISTINCT FROM p.organization_id OR g.ownership_scope IS DISTINCT FROM p.ownership_scope LIMIT 1""",
    ),
    (
        "assistant_llm_executions",
        """SELECT e.llm_execution_id FROM ai.assistant_llm_executions e LEFT JOIN ai.assistant_llm_invocation_plans g ON g.gateway_id=e.gateway_id LEFT JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=e.prompt_package_id WHERE g.gateway_id IS NULL OR p.prompt_package_id IS NULL OR e.prompt_package_id IS DISTINCT FROM g.prompt_package_id OR e.assistant_id IS DISTINCT FROM g.assistant_id OR e.assistant_session_id IS DISTINCT FROM g.assistant_session_id OR e.organization_id IS DISTINCT FROM g.organization_id OR e.ownership_scope IS DISTINCT FROM g.ownership_scope OR p.assistant_session_id IS DISTINCT FROM e.assistant_session_id OR p.organization_id IS DISTINCT FROM e.organization_id OR p.ownership_scope IS DISTINCT FROM e.ownership_scope OR p.assistant_id IS DISTINCT FROM e.assistant_id LIMIT 1""",
    ),
    (
        "assistant_citation_verifications",
        """SELECT v.citation_verification_id FROM ai.assistant_citation_verifications v LEFT JOIN ai.assistant_llm_executions e ON e.llm_execution_id=v.llm_execution_id LEFT JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=v.prompt_package_id LEFT JOIN ai.assistant_context_packages c ON c.context_package_id=v.context_package_id WHERE e.llm_execution_id IS NULL OR p.prompt_package_id IS NULL OR c.context_package_id IS NULL OR e.prompt_package_id IS DISTINCT FROM p.prompt_package_id OR p.context_package_id IS DISTINCT FROM c.context_package_id OR v.organization_id IS DISTINCT FROM e.organization_id OR v.ownership_scope IS DISTINCT FROM e.ownership_scope OR p.organization_id IS DISTINCT FROM e.organization_id OR c.organization_id IS DISTINCT FROM e.organization_id OR p.ownership_scope IS DISTINCT FROM e.ownership_scope OR c.ownership_scope IS DISTINCT FROM e.ownership_scope OR p.assistant_id IS DISTINCT FROM e.assistant_id OR c.assistant_id IS DISTINCT FROM e.assistant_id OR p.assistant_session_id IS DISTINCT FROM e.assistant_session_id OR c.assistant_session_id IS DISTINCT FROM e.assistant_session_id LIMIT 1""",
    ),
    (
        "assistant_responses",
        """SELECT r.assistant_response_id FROM ai.assistant_responses r LEFT JOIN ai.assistant_citation_verifications v ON v.citation_verification_id=r.citation_verification_id LEFT JOIN ai.assistant_llm_executions e ON e.llm_execution_id=r.llm_execution_id LEFT JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=r.prompt_package_id LEFT JOIN ai.assistant_context_packages c ON c.context_package_id=r.context_package_id WHERE v.citation_verification_id IS NULL OR e.llm_execution_id IS NULL OR p.prompt_package_id IS NULL OR c.context_package_id IS NULL OR v.llm_execution_id IS DISTINCT FROM r.llm_execution_id OR v.prompt_package_id IS DISTINCT FROM r.prompt_package_id OR v.context_package_id IS DISTINCT FROM r.context_package_id OR e.prompt_package_id IS DISTINCT FROM r.prompt_package_id OR p.context_package_id IS DISTINCT FROM r.context_package_id OR r.assistant_id IS DISTINCT FROM e.assistant_id OR r.assistant_session_id IS DISTINCT FROM e.assistant_session_id OR r.organization_id IS DISTINCT FROM e.organization_id OR r.ownership_scope IS DISTINCT FROM e.ownership_scope OR p.assistant_id IS DISTINCT FROM e.assistant_id OR c.assistant_id IS DISTINCT FROM e.assistant_id OR p.assistant_session_id IS DISTINCT FROM e.assistant_session_id OR c.assistant_session_id IS DISTINCT FROM e.assistant_session_id OR p.organization_id IS DISTINCT FROM e.organization_id OR c.organization_id IS DISTINCT FROM e.organization_id OR p.ownership_scope IS DISTINCT FROM e.ownership_scope OR c.ownership_scope IS DISTINCT FROM e.ownership_scope LIMIT 1""",
    ),
)

TABLES = tuple(table for table, _ in CHECKS)

UNIQUES = (
    (
        "assistant_search_executions",
        "uq_ai_assistant_search_executions_lineage",
        ["search_execution_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_context_packages",
        "uq_ai_assistant_context_packages_lineage",
        ["context_package_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_prompt_packages",
        "uq_ai_assistant_prompt_packages_lineage",
        ["prompt_package_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_llm_invocation_plans",
        "uq_ai_assistant_llm_invocation_plans_lineage",
        ["gateway_id", "assistant_id", "organization_id"],
    ),
)

FOREIGN_KEYS = (
    (
        "assistant_context_packages",
        "assistant_search_executions",
        "fk_ai_assistant_context_packages_scoped_search",
        ["search_execution_id", "assistant_id", "organization_id"],
        ["search_execution_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_prompt_packages",
        "assistant_context_packages",
        "fk_ai_assistant_prompt_packages_scoped_context",
        ["context_package_id", "assistant_id", "organization_id"],
        ["context_package_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_llm_invocation_plans",
        "assistant_prompt_packages",
        "fk_ai_assistant_llm_invocation_plans_scoped_prompt",
        ["prompt_package_id", "assistant_id", "organization_id"],
        ["prompt_package_id", "assistant_id", "organization_id"],
    ),
    (
        "assistant_llm_executions",
        "assistant_llm_invocation_plans",
        "fk_ai_assistant_llm_executions_scoped_plan",
        ["gateway_id", "assistant_id", "organization_id"],
        ["gateway_id", "assistant_id", "organization_id"],
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table, query in CHECKS:
        invalid_id = bind.execute(sa.text(query)).scalar_one_or_none()
        if invalid_id is not None:
            raise RuntimeError(
                f"Cannot enforce downstream assistant lineage: {table} contains incompatible historical row {invalid_id}. Resolve through a governed process before upgrading."
            )

    for table, name, columns in UNIQUES:
        op.create_unique_constraint(name, table, columns, schema="ai")
    for source, target, name, local_columns, remote_columns in FOREIGN_KEYS:
        op.create_foreign_key(
            name, source, target, local_columns, remote_columns, source_schema="ai", referent_schema="ai"
        )

    op.execute("""
    CREATE FUNCTION ai.enforce_assistant_downstream_lineage() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE bad boolean := false;
    BEGIN
      IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_search_executions' THEN
        SELECT EXISTS (SELECT 1 FROM ai.assistant_context_packages c
          WHERE c.search_execution_id=OLD.search_execution_id AND
            (c.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             c.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             c.organization_id IS DISTINCT FROM NEW.organization_id OR
             c.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.search_execution_id IS DISTINCT FROM OLD.search_execution_id)) INTO bad;
      ELSIF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_context_packages' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_search_executions s
          WHERE s.search_execution_id=NEW.search_execution_id AND s.assistant_id=NEW.assistant_id
            AND s.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
            AND s.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND s.ownership_scope=NEW.ownership_scope)
          OR EXISTS (SELECT 1 FROM ai.assistant_prompt_packages p
          WHERE p.context_package_id=OLD.context_package_id AND
            (p.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             p.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             p.organization_id IS DISTINCT FROM NEW.organization_id OR
             p.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.context_package_id IS DISTINCT FROM OLD.context_package_id)) INTO bad;
      ELSIF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_prompt_packages' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_context_packages c
          WHERE c.context_package_id=NEW.context_package_id AND c.assistant_id=NEW.assistant_id
            AND c.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
            AND c.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND c.ownership_scope=NEW.ownership_scope)
          OR EXISTS (SELECT 1 FROM ai.assistant_llm_invocation_plans g
          WHERE g.prompt_package_id=OLD.prompt_package_id AND
            (g.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             g.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             g.organization_id IS DISTINCT FROM NEW.organization_id OR
             g.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.prompt_package_id IS DISTINCT FROM OLD.prompt_package_id))
          OR EXISTS (SELECT 1 FROM ai.assistant_llm_executions e
          WHERE e.prompt_package_id=OLD.prompt_package_id AND
            (e.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             e.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             e.organization_id IS DISTINCT FROM NEW.organization_id OR
             e.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.prompt_package_id IS DISTINCT FROM OLD.prompt_package_id)) INTO bad;
      ELSIF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_llm_invocation_plans' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_prompt_packages p
          WHERE p.prompt_package_id=NEW.prompt_package_id AND p.assistant_id=NEW.assistant_id
            AND p.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
            AND p.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND p.ownership_scope=NEW.ownership_scope)
          OR EXISTS (SELECT 1 FROM ai.assistant_llm_executions e
          WHERE e.gateway_id=OLD.gateway_id AND
            (e.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             e.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             e.organization_id IS DISTINCT FROM NEW.organization_id OR
             e.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             e.prompt_package_id IS DISTINCT FROM NEW.prompt_package_id OR
             NEW.gateway_id IS DISTINCT FROM OLD.gateway_id)) INTO bad;
      ELSIF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_llm_executions' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_llm_invocation_plans g
          JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=NEW.prompt_package_id
          WHERE g.gateway_id=NEW.gateway_id AND g.prompt_package_id=NEW.prompt_package_id
            AND g.assistant_id=NEW.assistant_id AND g.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
            AND g.organization_id IS NOT DISTINCT FROM NEW.organization_id AND g.ownership_scope=NEW.ownership_scope
            AND p.assistant_id=NEW.assistant_id AND p.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id
            AND p.organization_id IS NOT DISTINCT FROM NEW.organization_id AND p.ownership_scope=NEW.ownership_scope)
          OR EXISTS (SELECT 1 FROM ai.assistant_citation_verifications v
          WHERE v.llm_execution_id=OLD.llm_execution_id AND
            (v.prompt_package_id IS DISTINCT FROM NEW.prompt_package_id OR
             v.organization_id IS DISTINCT FROM NEW.organization_id OR
             v.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.llm_execution_id IS DISTINCT FROM OLD.llm_execution_id))
          OR EXISTS (SELECT 1 FROM ai.assistant_responses r
          WHERE r.llm_execution_id=OLD.llm_execution_id AND
            (r.assistant_id IS DISTINCT FROM NEW.assistant_id OR
             r.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id OR
             r.organization_id IS DISTINCT FROM NEW.organization_id OR
             r.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.llm_execution_id IS DISTINCT FROM OLD.llm_execution_id)) INTO bad;
      ELSIF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'assistant_citation_verifications' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_llm_executions e
          JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=NEW.prompt_package_id
          JOIN ai.assistant_context_packages c ON c.context_package_id=NEW.context_package_id
          WHERE e.llm_execution_id=NEW.llm_execution_id AND e.prompt_package_id=NEW.prompt_package_id
            AND p.context_package_id=NEW.context_package_id AND e.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND e.ownership_scope=NEW.ownership_scope AND p.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND c.organization_id IS NOT DISTINCT FROM NEW.organization_id AND p.ownership_scope=NEW.ownership_scope
            AND c.ownership_scope=NEW.ownership_scope AND e.assistant_id=p.assistant_id AND e.assistant_id=c.assistant_id
            AND e.assistant_session_id IS NOT DISTINCT FROM p.assistant_session_id
            AND e.assistant_session_id IS NOT DISTINCT FROM c.assistant_session_id)
          OR EXISTS (SELECT 1 FROM ai.assistant_responses r
          WHERE r.citation_verification_id=OLD.citation_verification_id AND
            (r.llm_execution_id IS DISTINCT FROM NEW.llm_execution_id OR
             r.prompt_package_id IS DISTINCT FROM NEW.prompt_package_id OR
             r.context_package_id IS DISTINCT FROM NEW.context_package_id OR
             r.organization_id IS DISTINCT FROM NEW.organization_id OR
             r.ownership_scope IS DISTINCT FROM NEW.ownership_scope OR
             NEW.citation_verification_id IS DISTINCT FROM OLD.citation_verification_id)) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_context_packages' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_search_executions s WHERE s.search_execution_id=NEW.search_execution_id AND s.assistant_id=NEW.assistant_id AND s.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id AND s.organization_id IS NOT DISTINCT FROM NEW.organization_id AND s.ownership_scope=NEW.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_prompt_packages' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_context_packages c WHERE c.context_package_id=NEW.context_package_id AND c.assistant_id=NEW.assistant_id AND c.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id AND c.organization_id IS NOT DISTINCT FROM NEW.organization_id AND c.ownership_scope=NEW.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_llm_invocation_plans' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_prompt_packages p WHERE p.prompt_package_id=NEW.prompt_package_id AND p.assistant_id=NEW.assistant_id AND p.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id AND p.organization_id IS NOT DISTINCT FROM NEW.organization_id AND p.ownership_scope=NEW.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_llm_executions' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_llm_invocation_plans g JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=NEW.prompt_package_id WHERE g.gateway_id=NEW.gateway_id AND g.prompt_package_id=NEW.prompt_package_id AND g.assistant_id=NEW.assistant_id AND g.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id AND g.organization_id IS NOT DISTINCT FROM NEW.organization_id AND g.ownership_scope=NEW.ownership_scope AND p.assistant_id=NEW.assistant_id AND p.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id AND p.organization_id IS NOT DISTINCT FROM NEW.organization_id AND p.ownership_scope=NEW.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_citation_verifications' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_llm_executions e JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=NEW.prompt_package_id JOIN ai.assistant_context_packages c ON c.context_package_id=NEW.context_package_id WHERE e.llm_execution_id=NEW.llm_execution_id AND e.prompt_package_id=NEW.prompt_package_id AND p.context_package_id=NEW.context_package_id AND e.assistant_id=p.assistant_id AND e.assistant_id=c.assistant_id AND e.assistant_session_id IS NOT DISTINCT FROM p.assistant_session_id AND e.assistant_session_id IS NOT DISTINCT FROM c.assistant_session_id AND e.organization_id IS NOT DISTINCT FROM NEW.organization_id AND e.organization_id IS NOT DISTINCT FROM p.organization_id AND e.organization_id IS NOT DISTINCT FROM c.organization_id AND e.ownership_scope=NEW.ownership_scope AND e.ownership_scope=p.ownership_scope AND e.ownership_scope=c.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_responses' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_citation_verifications v JOIN ai.assistant_llm_executions e ON e.llm_execution_id=NEW.llm_execution_id JOIN ai.assistant_prompt_packages p ON p.prompt_package_id=NEW.prompt_package_id JOIN ai.assistant_context_packages c ON c.context_package_id=NEW.context_package_id WHERE v.citation_verification_id=NEW.citation_verification_id AND v.llm_execution_id=NEW.llm_execution_id AND v.prompt_package_id=NEW.prompt_package_id AND v.context_package_id=NEW.context_package_id AND e.prompt_package_id=NEW.prompt_package_id AND p.context_package_id=NEW.context_package_id AND NEW.assistant_id=e.assistant_id AND NEW.assistant_session_id IS NOT DISTINCT FROM e.assistant_session_id AND NEW.organization_id IS NOT DISTINCT FROM e.organization_id AND NEW.ownership_scope=e.ownership_scope AND e.assistant_id=p.assistant_id AND e.assistant_id=c.assistant_id AND e.assistant_session_id IS NOT DISTINCT FROM p.assistant_session_id AND e.assistant_session_id IS NOT DISTINCT FROM c.assistant_session_id AND e.organization_id IS NOT DISTINCT FROM p.organization_id AND e.organization_id IS NOT DISTINCT FROM c.organization_id AND e.ownership_scope=p.ownership_scope AND e.ownership_scope=c.ownership_scope) INTO bad;
      END IF;
      IF bad THEN RAISE EXCEPTION 'assistant downstream lineage mismatch on %', TG_TABLE_NAME; END IF;
      RETURN NEW;
    END $$""")
    for table in TABLES:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER ck_ai_{table}_downstream_lineage AFTER INSERT OR UPDATE ON ai.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ai.enforce_assistant_downstream_lineage()"
        )
    for table in (
        "assistant_search_executions",
        "assistant_context_packages",
        "assistant_prompt_packages",
        "assistant_llm_invocation_plans",
        "assistant_llm_executions",
        "assistant_citation_verifications",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER ck_ai_{table}_downstream_children AFTER UPDATE ON ai.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ai.enforce_assistant_downstream_lineage()"
        )


def downgrade() -> None:
    for table in (
        "assistant_search_executions",
        "assistant_context_packages",
        "assistant_prompt_packages",
        "assistant_llm_invocation_plans",
        "assistant_llm_executions",
        "assistant_citation_verifications",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS ck_ai_{table}_downstream_children ON ai.{table}")
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER ck_ai_{table}_downstream_lineage ON ai.{table}")
    op.execute("DROP FUNCTION ai.enforce_assistant_downstream_lineage()")
    for source, _target, name, _local, _remote in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, source, schema="ai", type_="foreignkey")
    for table, name, _columns in reversed(UNIQUES):
        op.drop_constraint(name, table, schema="ai", type_="unique")
