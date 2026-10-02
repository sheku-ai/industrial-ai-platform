"""assistant and conversation organization ownership

Revision ID: 20260712_880
Revises: 20260711_870
Create Date: 2026-07-12 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260712_880"
down_revision = "20260711_870"
branch_labels = None
depends_on = None


def _ownership_columns(table: str) -> None:
    op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True), schema="ai")
    op.add_column(
        table,
        sa.Column("ownership_scope", sa.String(length=32), server_default="legacy_unscoped", nullable=False),
        schema="ai",
    )
    op.add_column(
        table,
        sa.Column("data_origin", sa.String(length=32), server_default="legacy", nullable=False),
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
    op.create_index(f"ix_ai_{table}_organization", table, ["organization_id", "created_at"], schema="ai")
    op.create_index(f"ix_ai_{table}_origin", table, ["data_origin", "created_at"], schema="ai")


def upgrade() -> None:
    _ownership_columns("assistant_definitions")
    _ownership_columns("conversations")
    _ownership_columns("conversation_turns")

    op.execute(
        """
        UPDATE ai.assistant_definitions
        SET organization_id = (runtime_metadata->>'organization_id')::uuid,
            ownership_scope = 'organization'
        WHERE runtime_metadata ? 'organization_id'
          AND (runtime_metadata->>'organization_id') ~* '^[0-9a-f-]{36}$'
          AND EXISTS (
              SELECT 1 FROM core.organizations o
              WHERE o.id = (runtime_metadata->>'organization_id')::uuid
          )
        """
    )
    op.execute(
        """
        UPDATE ai.assistant_definitions a
        SET organization_id = o.id,
            ownership_scope = 'organization'
        FROM core.organizations o
        WHERE a.organization_id IS NULL
          AND (a.runtime_metadata->>'reference_tenant')::boolean IS TRUE
          AND (o.config->>'reference_tenant')::boolean IS TRUE
        """
    )
    op.execute(
        """
        UPDATE ai.assistant_definitions
        SET data_origin = CASE
            WHEN COALESCE((runtime_metadata->>'validation_generated')::boolean, false)
              OR runtime_metadata->>'scenario' IS NOT NULL
              OR runtime_metadata->>'validation_scenario' IS NOT NULL THEN 'validation'
            WHEN COALESCE((runtime_metadata->>'reference_tenant')::boolean, false)
              OR COALESCE((runtime_metadata->>'canonical_product_reference')::boolean, false) THEN 'reference'
            ELSE 'legacy'
        END
        """
    )
    op.execute(
        """
        UPDATE ai.conversations
        SET organization_id = (runtime_context->>'organization_id')::uuid,
            ownership_scope = 'organization'
        WHERE runtime_context ? 'organization_id'
          AND (runtime_context->>'organization_id') ~* '^[0-9a-f-]{36}$'
          AND EXISTS (
              SELECT 1 FROM core.organizations o
              WHERE o.id = (runtime_context->>'organization_id')::uuid
          )
        """
    )
    op.execute(
        """
        UPDATE ai.conversations c
        SET organization_id = a.organization_id,
            ownership_scope = 'organization'
        FROM ai.assistant_definitions a
        WHERE c.organization_id IS NULL
          AND c.assistant_id = a.assistant_id
          AND a.ownership_scope = 'organization'
        """
    )
    op.execute(
        """
        UPDATE ai.conversations c
        SET data_origin = CASE
            WHEN COALESCE((c.conversation_metadata->>'validation_generated')::boolean, false)
              OR c.conversation_metadata->>'validation_scenario' IS NOT NULL THEN 'validation'
            WHEN a.data_origin IN ('reference','validation') THEN a.data_origin
            ELSE 'legacy'
        END
        FROM ai.assistant_definitions a
        WHERE c.assistant_id = a.assistant_id
        """
    )
    op.execute(
        """
        UPDATE ai.conversation_turns t
        SET organization_id = c.organization_id,
            ownership_scope = c.ownership_scope,
            data_origin = c.data_origin
        FROM ai.conversations c
        WHERE t.conversation_id = c.conversation_id
        """
    )

    op.drop_constraint("uq_ai_assistant_definitions_key_version", "assistant_definitions", schema="ai", type_="unique")
    op.create_index(
        "uq_ai_assistant_definitions_org_key_version",
        "assistant_definitions",
        ["organization_id", "assistant_key", "assistant_version"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("ownership_scope = 'organization'"),
    )
    op.create_index(
        "uq_ai_assistant_definitions_global_key_version",
        "assistant_definitions",
        ["assistant_key", "assistant_version"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("ownership_scope = 'global'"),
    )
    op.create_index(
        "uq_ai_assistant_definitions_legacy_key_version",
        "assistant_definitions",
        ["assistant_key", "assistant_version"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("ownership_scope = 'legacy_unscoped'"),
    )
    op.create_check_constraint(
        "ck_ai_assistant_definitions_ownership",
        "assistant_definitions",
        "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
        "(ownership_scope IN ('global','legacy_unscoped') AND organization_id IS NULL)",
        schema="ai",
    )
    op.create_check_constraint(
        "ck_ai_assistant_definitions_origin",
        "assistant_definitions",
        "data_origin IN ('operational','reference','validation','legacy')",
        schema="ai",
    )
    for table in ("conversations", "conversation_turns"):
        op.create_check_constraint(
            f"ck_ai_{table}_ownership",
            table,
            "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
            "(ownership_scope = 'legacy_unscoped' AND organization_id IS NULL)",
            schema="ai",
        )
        op.create_check_constraint(
            f"ck_ai_{table}_origin",
            table,
            "data_origin IN ('operational','reference','validation','legacy')",
            schema="ai",
        )

    op.create_unique_constraint(
        "uq_ai_conversations_id_organization",
        "conversations",
        ["conversation_id", "organization_id"],
        schema="ai",
    )
    op.create_foreign_key(
        "fk_ai_conversation_turns_conversation_organization",
        "conversation_turns",
        "conversations",
        ["conversation_id", "organization_id"],
        ["conversation_id", "organization_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="CASCADE",
    )

    op.execute(
        """
        INSERT INTO security.permissions (id, resource, action, description, created_at, updated_at)
        VALUES
          (gen_random_uuid(), 'platform.assistants', 'read',
           'Read assistants and conversations in the authorized scope', now(), now()),
          (gen_random_uuid(), 'platform.assistants', 'administer',
           'Administer assistants and conversations in the authorized scope', now(), now())
        ON CONFLICT (resource, action) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO security.role_permissions (id, role_id, permission_id, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), rp.role_id, target.id, now(), now()
        FROM security.role_permissions rp
        JOIN security.permissions source ON source.id = rp.permission_id
        CROSS JOIN security.permissions target
        WHERE target.resource = 'platform.assistants'
          AND target.action = CASE WHEN source.action = 'administer' THEN 'administer' ELSE 'read' END
          AND source.resource = 'platform.security'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_conversation_turns_conversation_organization",
        "conversation_turns",
        schema="ai",
        type_="foreignkey",
    )
    op.drop_constraint("uq_ai_conversations_id_organization", "conversations", schema="ai", type_="unique")
    for table in ("conversation_turns", "conversations"):
        op.drop_constraint(f"ck_ai_{table}_origin", table, schema="ai", type_="check")
        op.drop_constraint(f"ck_ai_{table}_ownership", table, schema="ai", type_="check")
    op.drop_constraint("ck_ai_assistant_definitions_origin", "assistant_definitions", schema="ai", type_="check")
    op.drop_constraint("ck_ai_assistant_definitions_ownership", "assistant_definitions", schema="ai", type_="check")
    op.drop_index("uq_ai_assistant_definitions_legacy_key_version", table_name="assistant_definitions", schema="ai")
    op.drop_index("uq_ai_assistant_definitions_global_key_version", table_name="assistant_definitions", schema="ai")
    op.drop_index("uq_ai_assistant_definitions_org_key_version", table_name="assistant_definitions", schema="ai")
    op.create_unique_constraint(
        "uq_ai_assistant_definitions_key_version",
        "assistant_definitions",
        ["assistant_key", "assistant_version"],
        schema="ai",
    )
    for table in ("conversation_turns", "conversations", "assistant_definitions"):
        op.drop_index(f"ix_ai_{table}_origin", table_name=table, schema="ai")
        op.drop_index(f"ix_ai_{table}_organization", table_name=table, schema="ai")
        op.drop_constraint(f"fk_ai_{table}_organization", table, schema="ai", type_="foreignkey")
        op.drop_column(table, "data_origin", schema="ai")
        op.drop_column(table, "ownership_scope", schema="ai")
        op.drop_column(table, "organization_id", schema="ai")
