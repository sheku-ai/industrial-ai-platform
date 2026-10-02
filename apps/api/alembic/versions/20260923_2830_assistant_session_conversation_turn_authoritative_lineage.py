"""authoritative assistant session and conversation turn lineage

Revision ID: 20260923_2830
Revises: 20260923_2820
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_2830"
down_revision: str | Sequence[str] | None = "20260923_2820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRECHECKS = (
    (
        "assistant_sessions",
        """
        SELECT s.assistant_session_id
        FROM ai.assistant_sessions AS s
        LEFT JOIN ai.assistant_definitions AS a ON a.assistant_id = s.assistant_id
        WHERE a.assistant_id IS NULL
           OR s.ownership_scope IS DISTINCT FROM a.ownership_scope
           OR s.organization_id IS DISTINCT FROM a.organization_id
        LIMIT 1
        """,
    ),
    (
        "conversation_turns",
        """
        SELECT t.conversation_turn_id
        FROM ai.conversation_turns AS t
        LEFT JOIN ai.conversations AS c ON c.conversation_id = t.conversation_id
        WHERE c.conversation_id IS NULL
           OR t.organization_id IS DISTINCT FROM c.organization_id
           OR t.ownership_scope IS DISTINCT FROM c.ownership_scope
           OR t.assistant_id IS DISTINCT FROM c.assistant_id
           OR t.assistant_session_id IS DISTINCT FROM c.assistant_session_id
        LIMIT 1
        """,
    ),
    (
        "conversation_turns_response",
        """
        SELECT t.conversation_turn_id
        FROM ai.conversation_turns AS t
        JOIN ai.assistant_responses AS r ON r.assistant_response_id = t.assistant_response_id
        WHERE t.organization_id IS DISTINCT FROM r.organization_id
           OR t.ownership_scope IS DISTINCT FROM r.ownership_scope
           OR t.assistant_id IS DISTINCT FROM r.assistant_id
           OR t.assistant_session_id IS DISTINCT FROM r.assistant_session_id
        LIMIT 1
        """,
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for category, query in PRECHECKS:
        artifact_id = bind.execute(sa.text(query)).scalar_one_or_none()
        if artifact_id is not None:
            raise RuntimeError(
                f"Cannot enforce assistant authoritative lineage: {category} contains incompatible "
                f"historical row {artifact_id}; resolve through a governed process before upgrading."
            )
    op.execute("""
    CREATE FUNCTION ai.enforce_assistant_session_conversation_turn_lineage() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE bad boolean := false;
    BEGIN
      IF TG_TABLE_NAME = 'assistant_sessions' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_definitions a
          WHERE a.assistant_id=NEW.assistant_id
            AND a.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND a.ownership_scope=NEW.ownership_scope) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_definitions' THEN
        SELECT EXISTS (SELECT 1 FROM ai.assistant_sessions s
          WHERE s.assistant_id=OLD.assistant_id
            AND (s.organization_id IS DISTINCT FROM NEW.organization_id
              OR s.ownership_scope IS DISTINCT FROM NEW.ownership_scope)) INTO bad;
      ELSIF TG_TABLE_NAME = 'conversation_turns' THEN
        SELECT NOT EXISTS (SELECT 1 FROM ai.conversations c
          WHERE c.conversation_id=NEW.conversation_id
            AND c.organization_id IS NOT DISTINCT FROM NEW.organization_id
            AND c.ownership_scope=NEW.ownership_scope
            AND c.assistant_id IS NOT DISTINCT FROM NEW.assistant_id
            AND c.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id) INTO bad;
        IF NOT bad AND NEW.assistant_response_id IS NOT NULL THEN
          SELECT NOT EXISTS (SELECT 1 FROM ai.assistant_responses r
            WHERE r.assistant_response_id=NEW.assistant_response_id
              AND r.organization_id IS NOT DISTINCT FROM NEW.organization_id
              AND r.ownership_scope=NEW.ownership_scope
              AND r.assistant_id IS NOT DISTINCT FROM NEW.assistant_id
              AND r.assistant_session_id IS NOT DISTINCT FROM NEW.assistant_session_id) INTO bad;
        END IF;
      ELSIF TG_TABLE_NAME = 'conversations' THEN
        SELECT EXISTS (SELECT 1 FROM ai.conversation_turns t
          WHERE t.conversation_id=OLD.conversation_id
            AND (t.organization_id IS DISTINCT FROM NEW.organization_id
              OR t.ownership_scope IS DISTINCT FROM NEW.ownership_scope
              OR t.assistant_id IS DISTINCT FROM NEW.assistant_id
              OR t.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id)) INTO bad;
      ELSIF TG_TABLE_NAME = 'assistant_responses' THEN
        SELECT EXISTS (SELECT 1 FROM ai.conversation_turns t
          WHERE t.assistant_response_id=OLD.assistant_response_id
            AND (t.organization_id IS DISTINCT FROM NEW.organization_id
              OR t.ownership_scope IS DISTINCT FROM NEW.ownership_scope
              OR t.assistant_id IS DISTINCT FROM NEW.assistant_id
              OR t.assistant_session_id IS DISTINCT FROM NEW.assistant_session_id)) INTO bad;
      END IF;
      IF bad THEN RAISE EXCEPTION 'assistant session/conversation turn lineage mismatch on %', TG_TABLE_NAME; END IF;
      RETURN NEW;
    END $$""")
    for table, events in (
        ("assistant_sessions", "INSERT OR UPDATE"),
        ("assistant_definitions", "UPDATE"),
        ("conversation_turns", "INSERT OR UPDATE"),
        ("conversations", "UPDATE"),
        ("assistant_responses", "UPDATE"),
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER ck_ai_{table}_authoritative_lineage "
            f"AFTER {events} ON ai.{table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION ai.enforce_assistant_session_conversation_turn_lineage()"
        )


def downgrade() -> None:
    for table in (
        "assistant_responses",
        "conversations",
        "conversation_turns",
        "assistant_definitions",
        "assistant_sessions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS ck_ai_{table}_authoritative_lineage ON ai.{table}")
    op.execute("DROP FUNCTION ai.enforce_assistant_session_conversation_turn_lineage()")
