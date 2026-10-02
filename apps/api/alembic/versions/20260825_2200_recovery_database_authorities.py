"""add authoritative recovery database resource identities

Revision ID: 20260825_2200
Revises: 20260825_2100
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_2200"
down_revision: str | None = "20260825_2100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_runtime_backup_artifact_resource_type"
_NEW_RESOURCE_TYPES = (
    "postgresql",
    "platform_postgresql",
    "identity_postgresql",
    "object_storage",
    "application_configuration",
    "migration_manifest",
    "release_manifest",
    "other",
)
_OLD_RESOURCE_TYPES = (
    "postgresql",
    "object_storage",
    "application_configuration",
    "migration_manifest",
    "release_manifest",
    "other",
)


def _resource_type_check(values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"resource_type IN ({rendered})"


def upgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "backup_artifact_evidence",
        schema="runtime",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "backup_artifact_evidence",
        _resource_type_check(_NEW_RESOURCE_TYPES),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "backup_artifact_evidence",
        schema="runtime",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "backup_artifact_evidence",
        _resource_type_check(_OLD_RESOURCE_TYPES),
        schema="runtime",
    )
