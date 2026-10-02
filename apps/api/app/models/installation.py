from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class InstallationSetup(TimestampMixin, Base):
    __tablename__ = "installation_setups"
    __table_args__ = (
        UniqueConstraint("installation_instance_id", name="uq_installation_setups_instance"),
        CheckConstraint(
            "length(btrim(installation_instance_id)) > 0",
            name="ck_installation_setups_instance_not_blank",
        ),
        CheckConstraint("setup_schema_version > 0", name="ck_installation_setups_schema_version"),
        {"schema": "core"},
    )

    installation_setup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    installation_instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    setup_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class InstallationSetupEvidence(Base):
    __tablename__ = "installation_setup_evidence"
    __table_args__ = (
        UniqueConstraint(
            "installation_setup_id",
            "evidence_type",
            name="uq_installation_setup_evidence_type",
        ),
        CheckConstraint("evidence_version > 0", name="ck_installation_setup_evidence_version"),
        CheckConstraint(
            "evidence_type IN ('organization_configured','administrator_configured','preferences_configured')",
            name="ck_installation_setup_evidence_type",
        ),
        CheckConstraint("char_length(evidence_hash) = 64", name="ck_installation_setup_evidence_hash"),
        {"schema": "core"},
    )

    installation_setup_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    installation_setup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.installation_setups.installation_setup_id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class InstallationCompletionEvidence(Base):
    __tablename__ = "installation_completion_evidence"
    __table_args__ = (
        UniqueConstraint("installation_setup_id", name="uq_installation_completion_setup"),
        CheckConstraint("setup_schema_version > 0", name="ck_installation_completion_schema_version"),
        CheckConstraint("char_length(evidence_digest) = 64", name="ck_installation_completion_digest"),
        {"schema": "core"},
    )

    installation_completion_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    installation_setup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.installation_setups.installation_setup_id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    initial_identity_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    initial_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security.roles.id", ondelete="RESTRICT"), nullable=False
    )
    setup_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
