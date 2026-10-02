"""ai runtime registry foundation

Revision ID: 20260618_1510
Revises: 20260618_1500
Create Date: 2026-06-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260618_1510"
down_revision: Union[str, None] = "20260618_1500"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
    ]


def uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "providers",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=128), nullable=False),
        sa.Column("provider_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("health_state", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_providers_organization_id_organizations"),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        sa.UniqueConstraint("organization_id", "provider_key", name="uq_providers_org_provider_key"),
        schema="ai",
    )
    op.create_index("ix_providers_organization_status", "providers", ["organization_id", "status"], schema="ai")
    op.create_index("ix_providers_enabled", "providers", ["enabled"], schema="ai")
    op.create_index("ix_providers_health_state", "providers", ["health_state"], schema="ai")

    op.add_column("models", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True), schema="ai")
    op.add_column("models", sa.Column("model_key", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("models", sa.Column("display_name", sa.String(length=255), nullable=True), schema="ai")
    op.add_column("models", sa.Column("model_ref", sa.String(length=255), nullable=True), schema="ai")
    op.add_column("models", sa.Column("model_type", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("models", sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.add_column("models", sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.add_column("models", sa.Column("context_window", sa.Integer(), nullable=True), schema="ai")
    op.add_column("models", sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False), schema="ai")
    op.add_column("models", sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.create_foreign_key("fk_models_provider_id_providers", "models", "providers", ["provider_id"], ["id"], source_schema="ai", referent_schema="ai", ondelete="SET NULL")
    op.create_unique_constraint("uq_models_org_model_key", "models", ["organization_id", "model_key"], schema="ai")
    op.create_index("ix_models_provider_id", "models", ["provider_id"], schema="ai")
    op.create_index("ix_models_enabled", "models", ["enabled"], schema="ai")
    op.create_index("ix_models_model_type", "models", ["model_type"], schema="ai")

    op.add_column("prompts", sa.Column("prompt_key", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("display_name", sa.String(length=255), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("prompt_type", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("template", sa.Text(), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("template_format", sa.String(length=64), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False), schema="ai")
    op.add_column("prompts", sa.Column("version", sa.String(length=64), nullable=True), schema="ai")
    op.add_column("prompts", sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.create_unique_constraint("uq_prompts_org_prompt_key", "prompts", ["organization_id", "prompt_key"], schema="ai")
    op.create_index("ix_prompts_enabled", "prompts", ["enabled"], schema="ai")
    op.create_index("ix_prompts_prompt_type", "prompts", ["prompt_type"], schema="ai")

    op.add_column("guardrails", sa.Column("guardrail_key", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("guardrails", sa.Column("display_name", sa.String(length=255), nullable=True), schema="ai")
    op.add_column("guardrails", sa.Column("guardrail_type", sa.String(length=128), nullable=True), schema="ai")
    op.add_column("guardrails", sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.add_column("guardrails", sa.Column("enforcement_mode", sa.String(length=64), nullable=True), schema="ai")
    op.add_column("guardrails", sa.Column("fallback_behavior", sa.String(length=64), nullable=True), schema="ai")
    op.add_column("guardrails", sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False), schema="ai")
    op.add_column("guardrails", sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False), schema="ai")
    op.create_unique_constraint("uq_guardrails_org_guardrail_key", "guardrails", ["organization_id", "guardrail_key"], schema="ai")
    op.create_index("ix_guardrails_enabled", "guardrails", ["enabled"], schema="ai")
    op.create_index("ix_guardrails_guardrail_type", "guardrails", ["guardrail_type"], schema="ai")

    op.create_table(
        "runtime_profiles",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("profile_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("answer_mode", sa.String(length=64), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guardrail_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generation_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fallback_mode", sa.String(length=64), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"], name="fk_runtime_profiles_organization_id_organizations"),
        sa.ForeignKeyConstraint(["provider_id"], ["ai.providers.id"], name="fk_runtime_profiles_provider_id_providers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["ai.models.id"], name="fk_runtime_profiles_model_id_models", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_id"], ["ai.prompts.id"], name="fk_runtime_profiles_prompt_id_prompts", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["guardrail_id"], ["ai.guardrails.id"], name="fk_runtime_profiles_guardrail_id_guardrails", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_profiles"),
        sa.UniqueConstraint("organization_id", "profile_key", name="uq_runtime_profiles_org_profile_key"),
        schema="ai",
    )
    op.create_index("ix_runtime_profiles_organization_status", "runtime_profiles", ["organization_id", "status"], schema="ai")
    op.create_index("ix_runtime_profiles_answer_mode", "runtime_profiles", ["answer_mode"], schema="ai")
    op.create_index("ix_runtime_profiles_provider_id", "runtime_profiles", ["provider_id"], schema="ai")
    op.create_index("ix_runtime_profiles_model_id", "runtime_profiles", ["model_id"], schema="ai")
    op.create_index("ix_runtime_profiles_prompt_id", "runtime_profiles", ["prompt_id"], schema="ai")
    op.create_index("ix_runtime_profiles_guardrail_id", "runtime_profiles", ["guardrail_id"], schema="ai")
    op.create_index(
        "uq_runtime_profiles_active_default_answer_mode",
        "runtime_profiles",
        ["organization_id", "answer_mode"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("is_default = true AND status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_runtime_profiles_active_default_answer_mode", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_guardrail_id", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_prompt_id", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_model_id", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_provider_id", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_answer_mode", table_name="runtime_profiles", schema="ai")
    op.drop_index("ix_runtime_profiles_organization_status", table_name="runtime_profiles", schema="ai")
    op.drop_table("runtime_profiles", schema="ai")

    op.drop_index("ix_guardrails_guardrail_type", table_name="guardrails", schema="ai")
    op.drop_index("ix_guardrails_enabled", table_name="guardrails", schema="ai")
    op.drop_constraint("uq_guardrails_org_guardrail_key", "guardrails", schema="ai", type_="unique")
    op.drop_column("guardrails", "metadata", schema="ai")
    op.drop_column("guardrails", "enabled", schema="ai")
    op.drop_column("guardrails", "fallback_behavior", schema="ai")
    op.drop_column("guardrails", "enforcement_mode", schema="ai")
    op.drop_column("guardrails", "policy", schema="ai")
    op.drop_column("guardrails", "guardrail_type", schema="ai")
    op.drop_column("guardrails", "display_name", schema="ai")
    op.drop_column("guardrails", "guardrail_key", schema="ai")

    op.drop_index("ix_prompts_prompt_type", table_name="prompts", schema="ai")
    op.drop_index("ix_prompts_enabled", table_name="prompts", schema="ai")
    op.drop_constraint("uq_prompts_org_prompt_key", "prompts", schema="ai", type_="unique")
    op.drop_column("prompts", "metadata", schema="ai")
    op.drop_column("prompts", "version", schema="ai")
    op.drop_column("prompts", "enabled", schema="ai")
    op.drop_column("prompts", "template_format", schema="ai")
    op.drop_column("prompts", "template", schema="ai")
    op.drop_column("prompts", "prompt_type", schema="ai")
    op.drop_column("prompts", "display_name", schema="ai")
    op.drop_column("prompts", "prompt_key", schema="ai")

    op.drop_index("ix_models_model_type", table_name="models", schema="ai")
    op.drop_index("ix_models_enabled", table_name="models", schema="ai")
    op.drop_index("ix_models_provider_id", table_name="models", schema="ai")
    op.drop_constraint("uq_models_org_model_key", "models", schema="ai", type_="unique")
    op.drop_constraint("fk_models_provider_id_providers", "models", schema="ai", type_="foreignkey")
    op.drop_column("models", "metadata", schema="ai")
    op.drop_column("models", "enabled", schema="ai")
    op.drop_column("models", "context_window", schema="ai")
    op.drop_column("models", "configuration", schema="ai")
    op.drop_column("models", "capabilities", schema="ai")
    op.drop_column("models", "model_type", schema="ai")
    op.drop_column("models", "model_ref", schema="ai")
    op.drop_column("models", "display_name", schema="ai")
    op.drop_column("models", "model_key", schema="ai")
    op.drop_column("models", "provider_id", schema="ai")

    op.drop_index("ix_providers_health_state", table_name="providers", schema="ai")
    op.drop_index("ix_providers_enabled", table_name="providers", schema="ai")
    op.drop_index("ix_providers_organization_status", table_name="providers", schema="ai")
    op.drop_table("providers", schema="ai")
