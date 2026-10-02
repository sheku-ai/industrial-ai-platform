"""add governed organization AI provider and model configuration

Revision ID: 20260728_990
Revises: 20260716_980
Create Date: 2026-07-28 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260728_990"
down_revision = "20260716_980"
branch_labels = None
depends_on = None


PERMISSIONS = (
    ("ai.configuration", "read", "Read organization AI provider and model configuration."),
    ("ai.providers", "administer", "Administer organization AI provider configurations."),
    ("ai.models", "administer", "Administer organization AI model configurations."),
    ("ai.validation", "execute", "Validate organization AI provider and model configurations."),
)


def _register_permissions() -> None:
    statement = sa.text(
        """
        INSERT INTO security.permissions (
            id, resource, action, description, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(),
            :resource,
            :action,
            :description,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (resource, action) DO UPDATE
        SET description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    connection = op.get_bind()
    for resource, action, description in PERMISSIONS:
        connection.execute(
            statement,
            {"resource": resource, "action": action, "description": description},
        )


def upgrade() -> None:
    op.add_column("providers", sa.Column("description", sa.Text(), nullable=True), schema="ai")
    op.add_column(
        "providers",
        sa.Column("endpoint_url", sa.String(length=2048), nullable=True),
        schema="ai",
    )
    op.add_column(
        "providers",
        sa.Column("credential_resolver_type", sa.String(length=64), nullable=True),
        schema="ai",
    )
    op.add_column(
        "providers",
        sa.Column("credential_reference", sa.String(length=1024), nullable=True),
        schema="ai",
    )
    op.add_column(
        "providers",
        sa.Column(
            "lifecycle_status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "providers",
        sa.Column(
            "configuration_revision",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        schema="ai",
    )
    op.create_check_constraint(
        "ck_providers_providers_lifecycle_status",
        "providers",
        "lifecycle_status IN ('active', 'archived')",
        schema="ai",
    )
    op.create_index(
        "ix_providers_organization_lifecycle",
        "providers",
        ["organization_id", "lifecycle_status"],
        schema="ai",
    )

    op.add_column(
        "models",
        sa.Column(
            "lifecycle_status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "models",
        sa.Column(
            "configuration_revision",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "models",
        sa.Column(
            "default_scope",
            sa.String(length=64),
            server_default="organization",
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "models",
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="ai",
    )
    op.create_check_constraint(
        "ck_models_models_lifecycle_status",
        "models",
        "lifecycle_status IN ('active', 'archived')",
        schema="ai",
    )
    op.create_index(
        "ix_models_organization_lifecycle",
        "models",
        ["organization_id", "lifecycle_status"],
        schema="ai",
    )
    op.create_index(
        "uq_models_org_capability_scope_default",
        "models",
        ["organization_id", "model_type", "default_scope"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND lifecycle_status = 'active'"),
        schema="ai",
    )

    op.create_table(
        "model_provider_validation_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("validation_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("configuration_revision", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("sanitized_error", sa.String(length=512), nullable=True),
        sa.Column(
            "evidence_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_reference", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(subject_type = 'provider' AND provider_id IS NOT NULL AND model_id IS NULL) OR "
            "(subject_type = 'model' AND provider_id IS NULL AND model_id IS NOT NULL)",
            name="ck_model_provider_validation_single_subject",
        ),
        sa.CheckConstraint(
            "subject_type IN ('provider', 'model')",
            name="ck_model_provider_validation_subject_type",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_model_provider_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["core.organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["ai.providers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_id"], ["ai.models.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="ai",
    )
    op.create_index(
        "ix_model_provider_validation_provider_latest",
        "model_provider_validation_evidence",
        ["organization_id", "provider_id", "evaluated_at"],
        schema="ai",
    )
    op.create_index(
        "ix_model_provider_validation_model_latest",
        "model_provider_validation_evidence",
        ["organization_id", "model_id", "evaluated_at"],
        schema="ai",
    )

    _register_permissions()


def downgrade() -> None:
    op.drop_index(
        "ix_model_provider_validation_model_latest",
        table_name="model_provider_validation_evidence",
        schema="ai",
    )
    op.drop_index(
        "ix_model_provider_validation_provider_latest",
        table_name="model_provider_validation_evidence",
        schema="ai",
    )
    op.drop_table("model_provider_validation_evidence", schema="ai")

    op.drop_index(
        "uq_models_org_capability_scope_default",
        table_name="models",
        schema="ai",
    )
    op.drop_index("ix_models_organization_lifecycle", table_name="models", schema="ai")
    op.drop_constraint(
        "ck_models_models_lifecycle_status",
        "models",
        schema="ai",
        type_="check",
    )
    op.drop_column("models", "is_default", schema="ai")
    op.drop_column("models", "default_scope", schema="ai")
    op.drop_column("models", "configuration_revision", schema="ai")
    op.drop_column("models", "lifecycle_status", schema="ai")

    op.drop_index(
        "ix_providers_organization_lifecycle",
        table_name="providers",
        schema="ai",
    )
    op.drop_constraint(
        "ck_providers_providers_lifecycle_status",
        "providers",
        schema="ai",
        type_="check",
    )
    op.drop_column("providers", "configuration_revision", schema="ai")
    op.drop_column("providers", "lifecycle_status", schema="ai")
    op.drop_column("providers", "credential_reference", schema="ai")
    op.drop_column("providers", "credential_resolver_type", schema="ai")
    op.drop_column("providers", "endpoint_url", schema="ai")
    op.drop_column("providers", "description", schema="ai")

    connection = op.get_bind()
    for resource, action, _description in PERMISSIONS:
        connection.execute(
            sa.text(
                "DELETE FROM security.permissions "
                "WHERE resource = :resource AND action = :action"
            ),
            {"resource": resource, "action": action},
        )
