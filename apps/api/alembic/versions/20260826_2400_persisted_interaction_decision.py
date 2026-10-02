"""add persisted conversation interaction decisions

Revision ID: 20260826_2400
Revises: 20260826_2300
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_2400"
down_revision: str | None = "20260826_2300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ai_conversation_context_packages_id_organization_turn",
        "conversation_context_packages",
        ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
        schema="ai",
    )
    op.create_table(
        "conversation_routing_configurations",
        sa.Column("routing_configuration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="organization", nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column("configuration_version", sa.String(length=64), nullable=False),
        sa.Column("configuration_status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "intent_catalog",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "provider_chain",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "confidence_thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "fallback_behavior",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "context_window_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "semantic_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint(
            "routing_configuration_id",
            name="pk_ai_conversation_routing_configurations",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "configuration_version",
            name="uq_ai_conversation_routing_configurations_org_version",
        ),
        sa.UniqueConstraint(
            "routing_configuration_id",
            "organization_id",
            name="uq_ai_conversation_routing_configurations_id_organization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_conversation_routing_configurations_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_routing_configurations_ownership",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_routing_configurations_origin",
        ),
        sa.CheckConstraint(
            "configuration_status IN ('active','superseded','disabled')",
            name="ck_ai_conversation_routing_configurations_status",
        ),
        schema="ai",
    )
    op.create_index(
        "uq_ai_conversation_routing_configurations_active_org",
        "conversation_routing_configurations",
        ["organization_id"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("configuration_status = 'active'"),
    )
    op.create_index(
        "ix_ai_conversation_routing_configurations_hash",
        "conversation_routing_configurations",
        ["configuration_hash"],
        schema="ai",
    )
    op.create_table(
        "conversation_interaction_decisions",
        sa.Column("interaction_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="organization", nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("routing_configuration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("resolution_method", sa.String(length=64), nullable=False),
        sa.Column("resolution_provider", sa.String(length=64), nullable=False),
        sa.Column(
            "referenced_turn_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("conversation_context_required", sa.Boolean(), nullable=False),
        sa.Column("retrieval_required", sa.Boolean(), nullable=False),
        sa.Column("generation_required", sa.Boolean(), nullable=False),
        sa.Column("target_runtime", sa.String(length=128), nullable=False),
        sa.Column("embedding_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("slm_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("router_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint(
            "interaction_decision_id",
            name="pk_ai_conversation_interaction_decisions",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_interaction_decisions_org_turn",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_conversation_interaction_decisions_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_turn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_context",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["routing_configuration_id", "organization_id"],
            [
                "ai.conversation_routing_configurations.routing_configuration_id",
                "ai.conversation_routing_configurations.organization_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_configuration",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_interaction_decisions_ownership",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_interaction_decisions_origin",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_conversation_interaction_decisions_confidence",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_decisions_conversation",
        "conversation_interaction_decisions",
        ["organization_id", "conversation_id", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_decisions_intent",
        "conversation_interaction_decisions",
        ["intent", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_decisions_input_hash",
        "conversation_interaction_decisions",
        ["input_hash"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_interaction_decisions_decision_hash",
        "conversation_interaction_decisions",
        ["decision_hash"],
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_conversation_interaction_decisions_decision_hash",
        table_name="conversation_interaction_decisions",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_decisions_input_hash",
        table_name="conversation_interaction_decisions",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_decisions_intent",
        table_name="conversation_interaction_decisions",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_interaction_decisions_conversation",
        table_name="conversation_interaction_decisions",
        schema="ai",
    )
    op.drop_table("conversation_interaction_decisions", schema="ai")
    op.drop_index(
        "ix_ai_conversation_routing_configurations_hash",
        table_name="conversation_routing_configurations",
        schema="ai",
    )
    op.drop_index(
        "uq_ai_conversation_routing_configurations_active_org",
        table_name="conversation_routing_configurations",
        schema="ai",
    )
    op.drop_table("conversation_routing_configurations", schema="ai")
    op.drop_constraint(
        "uq_ai_conversation_context_packages_id_organization_turn",
        "conversation_context_packages",
        schema="ai",
        type_="unique",
    )
