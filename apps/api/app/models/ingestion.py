import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class IngestionPipelineProfile(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    AuditColumnsMixin,
    Base,
):
    __tablename__ = "ingestion_pipeline_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            "revision",
            name="uq_ingestion_pipeline_profiles_org_code_revision",
        ),
        Index(
            "ix_ingestion_pipeline_profiles_org_enabled",
            "organization_id",
            "enabled",
        ),
        {"schema": "documents"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deployment_edition: Mapped[str] = mapped_column(
        String(32),
        default="community",
        nullable=False,
    )
    default_adapter_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    adapter_policies: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    adapter_versions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    adapter_settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
