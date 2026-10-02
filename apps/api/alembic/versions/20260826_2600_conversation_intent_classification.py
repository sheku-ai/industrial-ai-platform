"""add conversation intent model registry and classification evidence

Revision ID: 20260826_2600
Revises: 20260826_2500
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_2600"
down_revision: str | None = "20260826_2500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_intent_models",
        sa.Column("intent_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), server_default="global", nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column(
            "model_family",
            sa.String(length=64),
            server_default="conversation_intent",
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("model_status", sa.String(length=32), nullable=False),
        sa.Column("artifact_reference", sa.String(length=512), nullable=False),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("intent_model_id", name="pk_ai_conversation_intent_models"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_conversation_intent_models_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "organization_node_id"],
            ["core.organization_nodes.organization_id", "core.organization_nodes.id"],
            name="fk_ai_conversation_intent_models_scoped_node",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(scope_type = 'community' AND organization_id IS NULL "
            "AND organization_node_id IS NULL AND ownership_scope = 'global') OR "
            "(scope_type = 'organization' AND organization_id IS NOT NULL "
            "AND organization_node_id IS NULL AND ownership_scope = 'organization') OR "
            "(scope_type = 'organization_node' AND organization_id IS NOT NULL "
            "AND organization_node_id IS NOT NULL AND ownership_scope = 'organization')",
            name="ck_ai_conversation_intent_models_scope_ownership",
        ),
        sa.CheckConstraint(
            "scope_type IN ('community','organization','organization_node')",
            name="ck_ai_conversation_intent_models_scope_type",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_intent_models_origin",
        ),
        sa.CheckConstraint(
            "model_status IN ('registered','candidate','active','retired','failed')",
            name="ck_ai_conversation_intent_models_status",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_ai_conversation_intent_models_provider",
        ),
        sa.CheckConstraint(
            "length(trim(model_version)) > 0",
            name="ck_ai_conversation_intent_models_version",
        ),
        sa.CheckConstraint(
            "char_length(artifact_hash) = 64",
            name="ck_ai_conversation_intent_models_artifact_hash",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_intent_models_family",
        "conversation_intent_models",
        ["model_family"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_intent_models_provider",
        "conversation_intent_models",
        ["provider"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_intent_models_status",
        "conversation_intent_models",
        ["model_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_intent_models_organization",
        "conversation_intent_models",
        ["organization_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_conversation_intent_models_organization_node",
        "conversation_intent_models",
        ["organization_id", "organization_node_id"],
        schema="ai",
    )
    op.create_index(
        "uq_ai_conversation_intent_models_active_community_family",
        "conversation_intent_models",
        ["model_family"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("scope_type = 'community' AND model_status = 'active'"),
    )
    op.create_index(
        "uq_ai_conversation_intent_models_active_organization_family",
        "conversation_intent_models",
        ["organization_id", "model_family"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("scope_type = 'organization' AND model_status = 'active'"),
    )
    op.create_index(
        "uq_ai_conversation_intent_models_active_node_family",
        "conversation_intent_models",
        ["organization_id", "organization_node_id", "model_family"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("scope_type = 'organization_node' AND model_status = 'active'"),
    )

    op.create_table(
        "conversation_intent_classification_evidence",
        sa.Column("classification_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="organization", nullable=False),
        sa.Column("data_origin", sa.String(length=32), server_default="operational", nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_context_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intent_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("predicted_intent", sa.String(length=64), nullable=False),
        sa.Column("predicted_sub_intent", sa.String(length=64), nullable=True),
        sa.Column(
            "predicted_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("resolution_method", sa.String(length=64), nullable=False),
        sa.Column("resolution_provider", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("model_scope_type", sa.String(length=32), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("classification_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint(
            "classification_evidence_id",
            name="pk_ai_conversation_intent_classification_evidence",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_intent_classification_evidence_org_turn",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            name="fk_ai_intent_classification_evidence_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_intent_classification_evidence_scoped_turn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_intent_classification_evidence_scoped_context",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["intent_model_id"],
            ["ai.conversation_intent_models.intent_model_id"],
            name="fk_ai_intent_classification_evidence_model",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_intent_classification_evidence_ownership",
        ),
        sa.CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_intent_classification_evidence_origin",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_intent_classification_evidence_confidence",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_intent_classification_evidence_conversation",
        "conversation_intent_classification_evidence",
        ["organization_id", "conversation_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_intent_classification_evidence_model",
        "conversation_intent_classification_evidence",
        ["intent_model_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_intent_classification_evidence_intent",
        "conversation_intent_classification_evidence",
        ["predicted_intent"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_intent_classification_evidence_input_hash",
        "conversation_intent_classification_evidence",
        ["input_hash"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_intent_classification_evidence_hash",
        "conversation_intent_classification_evidence",
        ["classification_hash"],
        schema="ai",
    )

    op.add_column(
        "conversation_interaction_decisions",
        sa.Column("classification_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="ai",
    )
    op.add_column(
        "conversation_interaction_decisions",
        sa.Column("sub_intent", sa.String(length=64), nullable=True),
        schema="ai",
    )
    op.add_column(
        "conversation_interaction_decisions",
        sa.Column(
            "intent_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="ai",
    )
    op.create_foreign_key(
        "fk_ai_conversation_interaction_decisions_classification",
        "conversation_interaction_decisions",
        "conversation_intent_classification_evidence",
        ["classification_evidence_id"],
        ["classification_evidence_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_conversation_interaction_decisions_classification",
        "conversation_interaction_decisions",
        schema="ai",
        type_="foreignkey",
    )
    op.drop_column("conversation_interaction_decisions", "intent_parameters", schema="ai")
    op.drop_column("conversation_interaction_decisions", "sub_intent", schema="ai")
    op.drop_column("conversation_interaction_decisions", "classification_evidence_id", schema="ai")

    op.drop_index(
        "ix_ai_intent_classification_evidence_hash",
        table_name="conversation_intent_classification_evidence",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_intent_classification_evidence_input_hash",
        table_name="conversation_intent_classification_evidence",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_intent_classification_evidence_intent",
        table_name="conversation_intent_classification_evidence",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_intent_classification_evidence_model",
        table_name="conversation_intent_classification_evidence",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_intent_classification_evidence_conversation",
        table_name="conversation_intent_classification_evidence",
        schema="ai",
    )
    op.drop_table("conversation_intent_classification_evidence", schema="ai")

    op.drop_index(
        "uq_ai_conversation_intent_models_active_node_family",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "uq_ai_conversation_intent_models_active_organization_family",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "uq_ai_conversation_intent_models_active_community_family",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_intent_models_organization_node",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_intent_models_organization",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_intent_models_status",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_intent_models_provider",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_conversation_intent_models_family",
        table_name="conversation_intent_models",
        schema="ai",
    )
    op.drop_table("conversation_intent_models", schema="ai")
