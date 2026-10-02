from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuntimeConfigurationScope(StrEnum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    WORKER = "worker"
    WORKLOAD_CLASS = "workload_class"


class RuntimeConfigurationRevisionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISABLED = "disabled"


class RuntimeConfiguration(Base):
    """Stable identity and resolution scope for a runtime configuration key."""

    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_runtime_configurations_tenant_id",
        ),
        UniqueConstraint(
            "organization_id",
            "scope_type",
            "scope_key",
            "configuration_type",
            "configuration_key",
            name="uq_runtime_configurations_scope_key",
        ),
        CheckConstraint(
            "length(btrim(configuration_type)) > 0",
            name="ck_runtime_configurations_type_not_blank",
        ),
        CheckConstraint(
            "length(btrim(configuration_key)) > 0",
            name="ck_runtime_configurations_key_not_blank",
        ),
        CheckConstraint(
            "scope_type IN ('platform','organization','worker','workload_class')",
            name="ck_runtime_configurations_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'platform' AND organization_id IS NULL AND scope_key IS NULL) OR "
            "(scope_type = 'organization' AND organization_id IS NOT NULL AND scope_key IS NULL) OR "
            "(scope_type IN ('worker','workload_class') AND scope_key IS NOT NULL AND length(btrim(scope_key)) > 0)",
            name="ck_runtime_configurations_scope_shape",
        ),
        Index(
            "uq_runtime_configurations_platform_scope",
            "configuration_type",
            "configuration_key",
            unique=True,
            postgresql_where=text("scope_type = 'platform'"),
        ),
        Index(
            "uq_runtime_configurations_organization_scope",
            "organization_id",
            "configuration_type",
            "configuration_key",
            unique=True,
            postgresql_where=text("scope_type = 'organization'"),
        ),
        Index(
            "uq_runtime_configurations_named_platform_scope",
            "scope_type",
            "scope_key",
            "configuration_type",
            "configuration_key",
            unique=True,
            postgresql_where=text("scope_type IN ('worker','workload_class') AND organization_id IS NULL"),
        ),
        Index(
            "uq_runtime_configurations_named_organization_scope",
            "organization_id",
            "scope_type",
            "scope_key",
            "configuration_type",
            "configuration_key",
            unique=True,
            postgresql_where=text("scope_type IN ('worker','workload_class') AND organization_id IS NOT NULL"),
        ),
        Index(
            "ix_runtime_configurations_resolution",
            "configuration_type",
            "configuration_key",
            "scope_type",
            "organization_id",
            "scope_key",
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id", name="fk_runtime_configurations_organization"),
        nullable=True,
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    configuration_type: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RuntimeConfigurationRevision(Base):
    """Append-only versioned payload for a runtime configuration identity."""

    __tablename__ = "configuration_revisions"
    __table_args__ = (
        UniqueConstraint(
            "configuration_id",
            "revision",
            name="uq_runtime_configuration_revisions_number",
        ),
        UniqueConstraint(
            "configuration_id",
            "id",
            name="uq_runtime_configuration_revisions_configuration_id",
        ),
        ForeignKeyConstraint(
            ["organization_id", "configuration_id"],
            [
                "runtime.configurations.organization_id",
                "runtime.configurations.id",
            ],
            name="fk_runtime_configuration_revisions_tenant_configuration",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_runtime_configuration_revisions_positive_revision",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_runtime_configuration_revisions_positive_schema_version",
        ),
        CheckConstraint(
            "status IN ('draft','active','superseded','disabled')",
            name="ck_runtime_configuration_revisions_status",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_runtime_configuration_revisions_effective_window",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_runtime_configuration_revisions_payload_object",
        ),
        Index(
            "uq_runtime_configuration_revisions_active",
            "configuration_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_runtime_configuration_revisions_effective",
            "configuration_id",
            "status",
            "effective_from",
            "effective_until",
        ),
        Index(
            "ix_runtime_configuration_revisions_schema",
            "configuration_id",
            "schema_version",
        ),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "runtime.configurations.id",
            name="fk_runtime_configuration_revisions_configuration",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="draft", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
