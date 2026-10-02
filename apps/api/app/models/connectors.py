import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConnectorType(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "connector_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_connector_types_code"),
        {"schema": "connectors"},
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    edition: Mapped[str] = mapped_column(String(32), default="community", nullable=False)
    connector_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    config_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)


class Connector(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_connectors_org_code"),
        CheckConstraint(
            "(credential_resolver_type IS NULL AND credential_reference IS NULL) OR "
            "(credential_resolver_type IS NOT NULL AND credential_reference IS NOT NULL)",
            name="connectors_credential_reference_pair",
        ),
        {"schema": "connectors"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    connector_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.connector_types.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    credential_resolver_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class ConnectorConfig(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "connector_configs"
    __table_args__ = {"schema": "connectors"}

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.connectors.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class ConnectorRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_runs"
    __table_args__ = (
        Index("uq_connector_runs_runtime_execution", "runtime_execution_id", unique=True),
        {"schema": "connectors"},
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.connectors.id"), nullable=False
    )
    runtime_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runtime.executions.id", name="fk_connector_runs_runtime_execution"),
        nullable=True,
    )
    run_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
