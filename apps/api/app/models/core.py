import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        Index("ix_core_organizations_slug", "slug", unique=True),
        {"schema": "core"},
    )

    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class OrganizationNode(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "organization_nodes"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_organization_nodes_org_code"),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_organization_nodes_organization_identity",
        ),
        {"schema": "core"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organization_nodes.id"), nullable=True
    )
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    position: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class OrganizationRelationship(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "organization_relationships"
    __table_args__ = {"schema": "core"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=False
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organization_nodes.id"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organization_nodes.id"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class OrganizationNodeType(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "organization_node_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_organization_node_types_code"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="organization_node_types_status",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_child_types) = 'array'",
            name="organization_node_types_allowed_children",
        ),
        CheckConstraint(
            "jsonb_typeof(presentation_metadata) = 'object'",
            name="organization_node_types_presentation",
        ),
        CheckConstraint(
            "edition IN ('community', 'enterprise')",
            name="organization_node_types_edition",
        ),
        Index("ix_core_organization_node_types_catalog", "status", "display_order"),
        {"schema": "core"},
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    allows_children: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_child_types: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    presentation_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_for_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    edition: Mapped[str] = mapped_column(String(32), default="community", nullable=False)


class OrganizationStructureAggregate(TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "organization_structure_aggregates"
    __table_args__ = (
        CheckConstraint(
            "revision >= 0",
            name="organization_structure_revision",
        ),
        {"schema": "core"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_mutation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
