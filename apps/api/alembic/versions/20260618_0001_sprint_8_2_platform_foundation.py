"""Sprint 8.2 persistent platform foundation

Revision ID: 20260618_0001
Revises:
Create Date: 2026-06-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision: str = "20260618_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMAS = ["core", "documents", "security", "connectors", "ai", "audit"]


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
    ]


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    for schema in SCHEMAS:
        bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    op.create_table(
        "organizations",
        uuid_pk(),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        schema="core",
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True, schema="core")

    op.create_table(
        "organization_nodes",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("position", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["parent_node_id"], ["core.organization_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_organization_nodes_org_code"),
        schema="core",
    )

    op.create_table(
        "organization_relationships",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["core.organization_nodes.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["core.organization_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )

    op.create_table(
        "document_types",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_document_types_org_code"),
        schema="documents",
    )

    op.create_table(
        "metadata_templates",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("schema_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["document_type_id"], ["documents.document_types.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_metadata_templates_org_code"),
        schema="documents",
    )

    op.create_table(
        "retention_policies",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )

    op.create_table(
        "classification_rules",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="documents",
    )

    op.create_table(
        "collections",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("vector_provider", sa.String(length=64), nullable=True),
        sa.Column("vector_collection_name", sa.String(length=255), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_collections_org_code"),
        schema="documents",
    )

    op.create_table(
        "roles",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_roles_org_code"),
        schema="security",
    )

    op.create_table(
        "permissions",
        uuid_pk(),
        sa.Column("resource", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        *audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource", "action", name="uq_permissions_resource_action"),
        schema="security",
    )

    op.create_table(
        "policies",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False, server_default="allow"),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_policies_org_code"),
        schema="security",
    )

    op.create_table(
        "role_assignments",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.String(length=64), nullable=False),
        sa.Column("principal_id", sa.String(length=255), nullable=False),
        sa.Column("scope_type", sa.String(length=64), nullable=True),
        sa.Column("scope_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["security.roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="security",
    )

    op.create_table(
        "connector_types",
        uuid_pk(),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("edition", sa.String(length=32), nullable=False, server_default="community"),
        sa.Column("connector_kind", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("config_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
        *audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_connector_types_code"),
        schema="connectors",
    )

    op.create_table(
        "connectors",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["connector_type_id"], ["connectors.connector_types.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_connectors_org_code"),
        schema="connectors",
    )

    op.create_table(
        "connector_configs",
        uuid_pk(),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *audit_columns(),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.connectors.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="connectors",
    )

    op.create_table(
        "connector_runs",
        uuid_pk(),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.connectors.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="connectors",
    )

    op.create_table(
        "models",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_models_org_code"),
        schema="ai",
    )

    op.create_table(
        "prompts",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_prompts_org_code"),
        schema="ai",
    )

    op.create_table(
        "agents",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["ai.models.id"]),
        sa.ForeignKeyConstraint(["prompt_id"], ["ai.prompts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_agents_org_code"),
        schema="ai",
    )

    op.create_table(
        "knowledge_sources",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["ai.agents.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["documents.collections.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="ai",
    )

    op.create_table(
        "guardrails",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_guardrails_org_code"),
        schema="ai",
    )

    op.create_table(
        "workflows",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        *audit_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_workflows_org_code"),
        schema="ai",
    )

    op.create_table(
        "audit_actions",
        uuid_pk(),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        *audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_audit_actions_code"),
        schema="audit",
    )

    op.create_table(
        "audit_events",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("resource_type", sa.String(length=128), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["audit.audit_actions.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )

    op.create_table(
        "audit_history",
        uuid_pk(),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["core.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )


def downgrade() -> None:
    op.drop_table("audit_history", schema="audit")
    op.drop_table("audit_events", schema="audit")
    op.drop_table("audit_actions", schema="audit")

    op.drop_table("workflows", schema="ai")
    op.drop_table("guardrails", schema="ai")
    op.drop_table("knowledge_sources", schema="ai")
    op.drop_table("agents", schema="ai")
    op.drop_table("prompts", schema="ai")
    op.drop_table("models", schema="ai")

    op.drop_table("connector_runs", schema="connectors")
    op.drop_table("connector_configs", schema="connectors")
    op.drop_table("connectors", schema="connectors")
    op.drop_table("connector_types", schema="connectors")

    op.drop_table("role_assignments", schema="security")
    op.drop_table("policies", schema="security")
    op.drop_table("permissions", schema="security")
    op.drop_table("roles", schema="security")

    op.drop_table("collections", schema="documents")
    op.drop_table("classification_rules", schema="documents")
    op.drop_table("retention_policies", schema="documents")
    op.drop_table("metadata_templates", schema="documents")
    op.drop_table("document_types", schema="documents")

    op.drop_table("organization_relationships", schema="core")
    op.drop_table("organization_nodes", schema="core")
    op.drop_index("ix_organizations_slug", table_name="organizations", schema="core")
    op.drop_table("organizations", schema="core")

    bind = op.get_bind()
    for schema in reversed(SCHEMAS):
        bind.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
