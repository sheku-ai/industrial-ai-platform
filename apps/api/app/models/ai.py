import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    AuditColumnsMixin,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Provider(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_key", name="uq_providers_org_provider_key"),
        Index("ix_providers_organization_status", "organization_id", "status"),
        Index("ix_providers_enabled", "enabled"),
        Index("ix_providers_health_state", "health_state"),
        Index("ix_providers_organization_lifecycle", "organization_id", "lifecycle_status"),
        CheckConstraint(
            "lifecycle_status IN ('active', 'archived')",
            name="providers_lifecycle_status",
        ),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    provider_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    credential_resolver_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    configuration_revision: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    health_state: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Model(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_models_org_code"),
        UniqueConstraint("organization_id", "model_key", name="uq_models_org_model_key"),
        Index("ix_models_provider_id", "provider_id"),
        Index("ix_models_enabled", "enabled"),
        Index("ix_models_model_type", "model_type"),
        Index("ix_models_organization_lifecycle", "organization_id", "lifecycle_status"),
        CheckConstraint(
            "lifecycle_status IN ('active', 'archived')",
            name="models_lifecycle_status",
        ),
        Index(
            "uq_models_org_capability_scope_default",
            "organization_id",
            "model_type",
            "default_scope",
            unique=True,
            postgresql_where=text("is_default = true AND lifecycle_status = 'active'"),
        ),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)

    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.providers.id", ondelete="SET NULL"), nullable=True
    )
    model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    configuration_revision: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    default_scope: Mapped[str] = mapped_column(String(64), default="organization", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ModelProviderValidationEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_provider_validation_evidence"
    __table_args__ = (
        CheckConstraint(
            "(subject_type = 'provider' AND provider_id IS NOT NULL AND model_id IS NULL) OR "
            "(subject_type = 'model' AND provider_id IS NULL AND model_id IS NOT NULL)",
            name="model_provider_validation_single_subject",
        ),
        CheckConstraint(
            "subject_type IN ('provider', 'model')",
            name="model_provider_validation_subject_type",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="model_provider_validation_status",
        ),
        Index(
            "ix_model_provider_validation_provider_latest",
            "organization_id",
            "provider_id",
            "evaluated_at",
        ),
        Index(
            "ix_model_provider_validation_model_latest",
            "organization_id",
            "model_id",
            "evaluated_at",
        ),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.providers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.models.id", ondelete="RESTRICT"),
        nullable=True,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sanitized_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    evidence_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Prompt(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_prompts_org_code"),
        UniqueConstraint("organization_id", "prompt_key", name="uq_prompts_org_prompt_key"),
        Index("ix_prompts_enabled", "enabled"),
        Index("ix_prompts_prompt_type", "prompt_type"),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    prompt_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_agents_org_code"),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai.models.id"), nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai.prompts.id"), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)


class KnowledgeSource(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = {"schema": "ai"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai.agents.id"), nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.collections.id"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class Guardrail(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "guardrails"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_guardrails_org_code"),
        UniqueConstraint("organization_id", "guardrail_key", name="uq_guardrails_org_guardrail_key"),
        Index("ix_guardrails_enabled", "enabled"),
        Index("ix_guardrails_guardrail_type", "guardrail_type"),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    guardrail_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guardrail_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enforcement_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_behavior: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_workflows_org_code"),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)


class RuntimeProfile(UUIDPrimaryKeyMixin, TimestampMixin, AuditColumnsMixin, Base):
    __tablename__ = "runtime_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_key", name="uq_runtime_profiles_org_profile_key"),
        Index("ix_runtime_profiles_organization_status", "organization_id", "status"),
        Index("ix_runtime_profiles_answer_mode", "answer_mode"),
        Index("ix_runtime_profiles_provider_id", "provider_id"),
        Index("ix_runtime_profiles_model_id", "model_id"),
        Index("ix_runtime_profiles_prompt_id", "prompt_id"),
        Index("ix_runtime_profiles_guardrail_id", "guardrail_id"),
        Index(
            "uq_runtime_profiles_active_default_answer_mode",
            "organization_id",
            "answer_mode",
            unique=True,
            postgresql_where=text("is_default = true AND status = 'active'"),
        ),
        {"schema": "ai"},
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id"), nullable=True
    )
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.models.id", ondelete="SET NULL"), nullable=True
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.prompts.id", ondelete="SET NULL"), nullable=True
    )
    guardrail_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.guardrails.id", ondelete="SET NULL"), nullable=True
    )
    generation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
