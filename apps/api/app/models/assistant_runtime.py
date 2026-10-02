from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssistantOwnedArtifactMixin:
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=True
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="legacy_unscoped", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="legacy", nullable=False)


class AssistantDefinition(Base):
    __tablename__ = "assistant_definitions"
    __table_args__ = (
        CheckConstraint(
            "assistant_status IN ('draft','prepared','active','disabled','failed')",
            name="ck_ai_assistant_definitions_status",
        ),
        CheckConstraint(
            "default_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')",
            name="ck_ai_assistant_definitions_search_mode",
        ),
        Index("ix_ai_assistant_definitions_key", "assistant_key"),
        Index("ix_ai_assistant_definitions_status", "assistant_status"),
        Index("ix_ai_assistant_definitions_organization", "organization_id", "created_at"),
        Index("ix_ai_assistant_definitions_origin", "data_origin", "created_at"),
        Index(
            "uq_ai_assistant_definitions_org_key_version",
            "organization_id",
            "assistant_key",
            "assistant_version",
            unique=True,
            postgresql_where=text("ownership_scope = 'organization'"),
        ),
        Index(
            "uq_ai_assistant_definitions_global_key_version",
            "assistant_key",
            "assistant_version",
            unique=True,
            postgresql_where=text("ownership_scope = 'global'"),
        ),
        Index(
            "uq_ai_assistant_definitions_legacy_key_version",
            "assistant_key",
            "assistant_version",
            unique=True,
            postgresql_where=text("ownership_scope = 'legacy_unscoped'"),
        ),
        CheckConstraint(
            "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
            "(ownership_scope IN ('global','legacy_unscoped') AND organization_id IS NULL)",
            name="ck_ai_assistant_definitions_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_assistant_definitions_origin",
        ),
        {"schema": "ai"},
    )

    assistant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT")
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="legacy_unscoped", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="legacy", nullable=False)
    assistant_key: Mapped[str] = mapped_column(String(128), nullable=False)
    assistant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    assistant_status: Mapped[str] = mapped_column(String(32), server_default="prepared", nullable=False)
    assistant_version: Mapped[str] = mapped_column(String(64), server_default="1.0", nullable=False)
    assistant_type: Mapped[str] = mapped_column(String(128), server_default="platform_assistant", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_search_mode: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    allowed_runtime_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=text("ARRAY[]::varchar[]"), nullable=False
    )
    guardrail_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantSession(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_sessions"
    __table_args__ = (
        UniqueConstraint(
            "assistant_session_id",
            "organization_id",
            name="uq_ai_assistant_sessions_id_organization",
        ),
        UniqueConstraint(
            "assistant_session_id",
            "assistant_id",
            "organization_id",
            name="uq_ai_assistant_sessions_id_assistant_organization",
        ),
        CheckConstraint(
            "session_status IN ('prepared','planned','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_sessions_status",
        ),
        Index("ix_ai_assistant_sessions_assistant", "assistant_id", "created_at"),
        Index("ix_ai_assistant_sessions_status", "session_status"),
        {"schema": "ai"},
    )

    assistant_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    session_status: Mapped[str] = mapped_column(String(32), server_default="prepared", nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    conversation_reference: Mapped[str | None] = mapped_column(String(255))
    runtime_context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantRuntimeRun(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_runtime_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assistant_session_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_sessions.assistant_session_id",
                "ai.assistant_sessions.assistant_id",
                "ai.assistant_sessions.organization_id",
            ],
            name="fk_ai_assistant_runtime_runs_scoped_session",
        ),
        CheckConstraint(
            "run_status IN ('prepared','planned','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_runtime_runs_status",
        ),
        CheckConstraint(
            "execution_state IN ('metadata_only','planned','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_runtime_runs_execution_state",
        ),
        CheckConstraint(
            "selected_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')",
            name="ck_ai_assistant_runtime_runs_search_mode",
        ),
        Index("ix_ai_assistant_runtime_runs_assistant", "assistant_id", "created_at"),
        Index("ix_ai_assistant_runtime_runs_session", "assistant_session_id", "created_at"),
        Index("ix_ai_assistant_runtime_runs_status", "run_status"),
        Index("ix_ai_assistant_runtime_runs_recovery_lease", "recovery_state", "recovery_lease_expires_at"),
        CheckConstraint(
            "(recovery_state IS NULL AND recovery_owner IS NULL AND recovery_lease_expires_at IS NULL "
            "AND recovery_generation IS NULL) OR "
            "(recovery_state = 'claimed' AND recovery_owner IS NOT NULL "
            "AND recovery_lease_expires_at IS NOT NULL AND recovery_generation > 0) OR "
            "(recovery_state IN ('uncertain','completed','failed','blocked') "
            "AND recovery_owner IS NULL AND recovery_lease_expires_at IS NULL AND recovery_generation > 0)",
            name="ck_ai_assistant_runtime_runs_recovery_claim",
        ),
        {"schema": "ai"},
    )

    assistant_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="CASCADE"), nullable=False
    )
    run_status: Mapped[str] = mapped_column(String(32), server_default="planned", nullable=False)
    requested_query: Mapped[str | None] = mapped_column(Text)
    selected_search_mode: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    selected_runtime_domain: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), server_default="metadata_only", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    recovery_state: Mapped[str | None] = mapped_column(String(32))
    recovery_owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recovery_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_generation: Mapped[int | None] = mapped_column(Integer)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantRetrievalPlan(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_retrieval_plans"
    __table_args__ = (
        UniqueConstraint(
            "retrieval_plan_id",
            "assistant_id",
            "organization_id",
            name="uq_ai_assistant_retrieval_plans_lineage",
        ),
        ForeignKeyConstraint(
            ["assistant_session_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_sessions.assistant_session_id",
                "ai.assistant_sessions.assistant_id",
                "ai.assistant_sessions.organization_id",
            ],
            name="fk_ai_assistant_retrieval_plans_scoped_session",
        ),
        CheckConstraint(
            "plan_status IN ('prepared','planned','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_retrieval_plans_status",
        ),
        CheckConstraint(
            "execution_state IN ('metadata_only','planned','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_retrieval_plans_execution_state",
        ),
        CheckConstraint(
            "selected_search_mode IN ('none','enterprise_search','semantic_search','hybrid_search')",
            name="ck_ai_assistant_retrieval_plans_search_mode",
        ),
        Index("ix_ai_assistant_retrieval_plans_assistant", "assistant_id", "created_at"),
        Index("ix_ai_assistant_retrieval_plans_session", "assistant_session_id", "created_at"),
        Index("ix_ai_assistant_retrieval_plans_status", "plan_status"),
        {"schema": "ai"},
    )

    retrieval_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    plan_status: Mapped[str] = mapped_column(String(32), server_default="planned", nullable=False)
    requested_query: Mapped[str | None] = mapped_column(Text)
    selected_search_mode: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    selected_runtime_domain: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), server_default="metadata_only", nullable=False)
    enterprise_search_planned: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    semantic_search_planned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    hybrid_search_planned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    retrieval_executed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantRetrievalExecutionPlan(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_retrieval_execution_plans"
    __table_args__ = (
        UniqueConstraint(
            "execution_plan_id",
            "retrieval_plan_id",
            "assistant_id",
            "organization_id",
            name="uq_ai_assistant_retrieval_execution_plans_lineage",
        ),
        ForeignKeyConstraint(
            ["retrieval_plan_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_retrieval_plans.retrieval_plan_id",
                "ai.assistant_retrieval_plans.assistant_id",
                "ai.assistant_retrieval_plans.organization_id",
            ],
            name="fk_ai_assistant_retrieval_execution_plans_scoped_plan",
        ),
        CheckConstraint(
            "execution_status IN ('prepared','blocked','failed','disabled')",
            name="ck_ai_assistant_retrieval_execution_plans_status",
        ),
        CheckConstraint(
            "execution_state IN ('readiness_only','blocked','failed','disabled')",
            name="ck_ai_assistant_retrieval_execution_plans_state",
        ),
        CheckConstraint(
            "selected_search_mode IN ('enterprise_search','semantic_search','hybrid_search')",
            name="ck_ai_assistant_retrieval_execution_plans_search_mode",
        ),
        Index("ix_ai_assistant_retrieval_execution_plans_retrieval", "retrieval_plan_id", "created_at"),
        Index("ix_ai_assistant_retrieval_execution_plans_assistant", "assistant_id", "created_at"),
        Index("ix_ai_assistant_retrieval_execution_plans_status", "execution_status"),
        {"schema": "ai"},
    )

    execution_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    retrieval_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_retrieval_plans.retrieval_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    execution_status: Mapped[str] = mapped_column(String(32), server_default="prepared", nullable=False)
    selected_search_mode: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    selected_runtime_domain: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), server_default="readiness_only", nullable=False)
    enterprise_search_execution_prepared: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    semantic_search_execution_prepared: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    hybrid_search_execution_prepared: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    retrieval_executed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    answer_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    llm_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    tool_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    workflow_executed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    external_action_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    autonomous_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    readiness_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantSearchExecution(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_search_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_plan_id", "retrieval_plan_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_retrieval_execution_plans.execution_plan_id",
                "ai.assistant_retrieval_execution_plans.retrieval_plan_id",
                "ai.assistant_retrieval_execution_plans.assistant_id",
                "ai.assistant_retrieval_execution_plans.organization_id",
            ],
            name="fk_ai_assistant_search_executions_scoped_execution",
        ),
        CheckConstraint("search_mode IN ('enterprise_search')", name="ck_ai_assistant_search_executions_mode"),
        CheckConstraint("runtime_domain IN ('enterprise_search')", name="ck_ai_assistant_search_executions_domain"),
        CheckConstraint(
            "search_duration_ms IS NULL OR search_duration_ms >= 0", name="ck_ai_assistant_search_executions_duration"
        ),
        CheckConstraint("result_count >= 0", name="ck_ai_assistant_search_executions_result_count"),
        Index("ix_ai_assistant_search_executions_execution_plan", "execution_plan_id", "created_at"),
        Index("ix_ai_assistant_search_executions_retrieval_plan", "retrieval_plan_id", "created_at"),
        Index("ix_ai_assistant_search_executions_assistant", "assistant_id", "created_at"),
        {"schema": "ai"},
    )

    search_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_retrieval_execution_plans.execution_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    retrieval_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_retrieval_plans.retrieval_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    search_mode: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    runtime_domain: Mapped[str] = mapped_column(String(64), server_default="enterprise_search", nullable=False)
    search_query: Mapped[str] = mapped_column(Text, nullable=False)
    search_completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    search_duration_ms: Mapped[int | None] = mapped_column(Integer)
    result_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    lexical_search_used: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    postgresql_fts_used: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    semantic_search_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    hybrid_search_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    qdrant_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    reranking_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    llm_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    answer_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    tool_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    workflow_executed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    external_action_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    autonomous_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantContextPackage(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_context_packages"
    __table_args__ = (
        UniqueConstraint(
            "context_package_id", "assistant_id", "organization_id", name="uq_ai_assistant_context_packages_lineage"
        ),
        ForeignKeyConstraint(
            ["search_execution_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_search_executions.search_execution_id",
                "ai.assistant_search_executions.assistant_id",
                "ai.assistant_search_executions.organization_id",
            ],
            name="fk_ai_assistant_context_packages_scoped_search",
        ),
        CheckConstraint(
            "package_status IN ('prepared','created','blocked','failed','disabled')",
            name="ck_ai_assistant_context_packages_status",
        ),
        CheckConstraint("chunk_count >= 0", name="ck_ai_assistant_context_packages_chunk_count"),
        CheckConstraint("citation_count >= 0", name="ck_ai_assistant_context_packages_citation_count"),
        CheckConstraint("total_tokens_estimated >= 0", name="ck_ai_assistant_context_packages_tokens"),
        CheckConstraint("context_size_bytes >= 0", name="ck_ai_assistant_context_packages_size"),
        Index("ix_ai_assistant_context_packages_search_execution", "search_execution_id", "created_at"),
        Index("ix_ai_assistant_context_packages_assistant", "assistant_id", "created_at"),
        {"schema": "ai"},
    )

    context_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_search_executions.search_execution_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    package_status: Mapped[str] = mapped_column(String(32), server_default="created", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    total_tokens_estimated: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    context_size_bytes: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    truncation_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    truncation_applied: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    ordered_context: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    ordered_citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    package_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantPromptPackage(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_prompt_packages"
    __table_args__ = (
        UniqueConstraint(
            "prompt_package_id", "assistant_id", "organization_id", name="uq_ai_assistant_prompt_packages_lineage"
        ),
        ForeignKeyConstraint(
            ["context_package_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_context_packages.context_package_id",
                "ai.assistant_context_packages.assistant_id",
                "ai.assistant_context_packages.organization_id",
            ],
            name="fk_ai_assistant_prompt_packages_scoped_context",
        ),
        CheckConstraint(
            "package_status IN ('prepared','created','blocked','failed','disabled')",
            name="ck_ai_assistant_prompt_packages_status",
        ),
        CheckConstraint("estimated_prompt_tokens >= 0", name="ck_ai_assistant_prompt_packages_tokens"),
        CheckConstraint("prompt_size_bytes >= 0", name="ck_ai_assistant_prompt_packages_size"),
        Index("ix_ai_assistant_prompt_packages_context", "context_package_id", "created_at"),
        Index("ix_ai_assistant_prompt_packages_assistant", "assistant_id", "created_at"),
        {"schema": "ai"},
    )

    prompt_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    context_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_context_packages.context_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    package_status: Mapped[str] = mapped_column(String(32), server_default="created", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    assembled_context: Mapped[str] = mapped_column(Text, nullable=False)
    citation_section: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_prompt_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    prompt_size_bytes: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    prompt_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    llm_ready: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    llm_invoked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    answer_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantLlmInvocationPlan(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_llm_invocation_plans"
    __table_args__ = (
        UniqueConstraint(
            "gateway_id", "assistant_id", "organization_id", name="uq_ai_assistant_llm_invocation_plans_lineage"
        ),
        ForeignKeyConstraint(
            ["prompt_package_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_prompt_packages.prompt_package_id",
                "ai.assistant_prompt_packages.assistant_id",
                "ai.assistant_prompt_packages.organization_id",
            ],
            name="fk_ai_assistant_llm_invocation_plans_scoped_prompt",
        ),
        CheckConstraint("planned_temperature >= 0", name="ck_ai_assistant_llm_invocation_plans_temperature"),
        CheckConstraint("planned_max_tokens > 0", name="ck_ai_assistant_llm_invocation_plans_max_tokens"),
        CheckConstraint("planned_top_p >= 0 AND planned_top_p <= 1", name="ck_ai_assistant_llm_invocation_plans_top_p"),
        CheckConstraint("planned_timeout > 0", name="ck_ai_assistant_llm_invocation_plans_timeout"),
        Index("ix_ai_assistant_llm_invocation_plans_prompt", "prompt_package_id", "created_at"),
        Index("ix_ai_assistant_llm_invocation_plans_assistant", "assistant_id", "created_at"),
        {"schema": "ai"},
    )

    gateway_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_prompt_packages.prompt_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    provider_type: Mapped[str] = mapped_column(String(64), server_default="reference", nullable=False)
    provider_name: Mapped[str] = mapped_column(String(128), server_default="metadata-only", nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), server_default="metadata-only", nullable=False)
    provider_ready: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    execution_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    blocked_reason: Mapped[str] = mapped_column(String(255), server_default="execution_disabled", nullable=False)
    planned_temperature: Mapped[float] = mapped_column(Float, server_default=text("0.0"), nullable=False)
    planned_max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("1024"), nullable=False)
    planned_top_p: Mapped[float] = mapped_column(Float, server_default=text("1.0"), nullable=False)
    planned_stop_sequences: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    planned_seed: Mapped[int | None] = mapped_column(Integer)
    planned_timeout: Mapped[int] = mapped_column(Integer, server_default=text("30"), nullable=False)
    llm_invoked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    answer_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    tool_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    workflow_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    external_action_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    autonomous_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    gateway_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantLlmExecution(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_llm_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gateway_id", "assistant_id", "organization_id"],
            [
                "ai.assistant_llm_invocation_plans.gateway_id",
                "ai.assistant_llm_invocation_plans.assistant_id",
                "ai.assistant_llm_invocation_plans.organization_id",
            ],
            name="fk_ai_assistant_llm_executions_scoped_plan",
        ),
        CheckConstraint(
            "execution_status IN ('prepared','running','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_llm_executions_status",
        ),
        CheckConstraint(
            "provider_call_mode IN ('deterministic_local_mock')", name="ck_ai_assistant_llm_executions_call_mode"
        ),
        CheckConstraint("prompt_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_prompt_tokens"),
        CheckConstraint("completion_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_completion_tokens"),
        CheckConstraint("total_tokens_estimated >= 0", name="ck_ai_assistant_llm_executions_total_tokens"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_assistant_llm_executions_latency"),
        Index("ix_ai_assistant_llm_executions_gateway", "gateway_id", "created_at"),
        Index("uq_ai_assistant_llm_executions_gateway_claim", "gateway_id", unique=True),
        Index(
            "uq_ai_assistant_llm_executions_runtime_claim",
            text("(request_payload_metadata ->> 'assistant_run_id')"),
            unique=True,
            postgresql_where=text("request_payload_metadata ? 'assistant_run_id'"),
        ),
        Index("ix_ai_assistant_llm_executions_prompt", "prompt_package_id", "created_at"),
        Index("ix_ai_assistant_llm_executions_assistant", "assistant_id", "created_at"),
        {"schema": "ai"},
    )

    llm_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gateway_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_llm_invocation_plans.gateway_id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_prompt_packages.prompt_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    provider_type: Mapped[str] = mapped_column(String(64), server_default="local_mock", nullable=False)
    provider_name: Mapped[str] = mapped_column(String(128), server_default="deterministic-local-mock", nullable=False)
    model_name: Mapped[str] = mapped_column(
        String(128), server_default="deterministic-assistant-runtime-mock", nullable=False
    )
    execution_status: Mapped[str] = mapped_column(String(32), server_default="completed", nullable=False)
    execution_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    provider_called: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    provider_call_mode: Mapped[str] = mapped_column(
        String(64), server_default="deterministic_local_mock", nullable=False
    )
    request_payload_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    raw_output_text: Mapped[str | None] = mapped_column(Text)
    raw_output_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    prompt_tokens_estimated: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    completion_tokens_estimated: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    total_tokens_estimated: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_call_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    citation_verification_completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    final_response_created: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    tool_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    workflow_executed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    external_action_called: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    autonomous_execution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantCitationVerification(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_citation_verifications"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('prepared','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_citation_verifications_status",
        ),
        CheckConstraint("verified_citation_count >= 0", name="ck_ai_assistant_citation_verifications_verified_count"),
        CheckConstraint("missing_citation_count >= 0", name="ck_ai_assistant_citation_verifications_missing_count"),
        CheckConstraint("invalid_citation_count >= 0", name="ck_ai_assistant_citation_verifications_invalid_count"),
        Index("uq_ai_assistant_citation_verifications_llm_execution", "llm_execution_id", unique=True),
        Index("ix_ai_assistant_citation_verifications_llm_execution", "llm_execution_id", "created_at"),
        Index("ix_ai_assistant_citation_verifications_prompt", "prompt_package_id", "created_at"),
        Index("ix_ai_assistant_citation_verifications_context", "context_package_id", "created_at"),
        {"schema": "ai"},
    )

    citation_verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assistant_runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_runtime_runs.assistant_run_id", ondelete="SET NULL")
    )
    llm_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_llm_executions.llm_execution_id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_prompt_packages.prompt_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    context_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_context_packages.context_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    verification_status: Mapped[str] = mapped_column(String(32), server_default="completed", nullable=False)
    verified_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    missing_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    invalid_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    verification_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssistantResponse(AssistantOwnedArtifactMixin, Base):
    __tablename__ = "assistant_responses"
    __table_args__ = (
        CheckConstraint(
            "response_status IN ('prepared','completed','blocked','failed','disabled')",
            name="ck_ai_assistant_responses_status",
        ),
        CheckConstraint("verified_citation_count >= 0", name="ck_ai_assistant_responses_verified_count"),
        CheckConstraint("missing_citation_count >= 0", name="ck_ai_assistant_responses_missing_count"),
        CheckConstraint("invalid_citation_count >= 0", name="ck_ai_assistant_responses_invalid_count"),
        UniqueConstraint(
            "citation_verification_id",
            name="uq_ai_assistant_responses_citation_verification",
        ),
        Index("ix_ai_assistant_responses_citation_verification", "citation_verification_id", "created_at"),
        Index("ix_ai_assistant_responses_llm_execution", "llm_execution_id", "created_at"),
        Index("ix_ai_assistant_responses_assistant", "assistant_id", "created_at"),
        Index("ix_ai_assistant_responses_session", "assistant_session_id", "created_at"),
        {"schema": "ai"},
    )

    assistant_response_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    citation_verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_citation_verifications.citation_verification_id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_llm_executions.llm_execution_id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_prompt_packages.prompt_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    context_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai.assistant_context_packages.context_package_id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="CASCADE"), nullable=False
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    response_status: Mapped[str] = mapped_column(String(32), server_default="completed", nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_format: Mapped[str] = mapped_column(String(64), server_default="markdown", nullable=False)
    response_language: Mapped[str] = mapped_column(String(64), server_default="unknown", nullable=False)
    citation_verification_passed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    verified_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    missing_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    invalid_citation_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    ordered_citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationContextPackage(Base):
    __tablename__ = "conversation_context_packages"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_context_packages_organization_turn",
        ),
        UniqueConstraint(
            "conversation_context_package_id",
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_context_packages_id_organization_turn",
        ),
        ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_context_packages_scoped_turn",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_context_packages_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_context_packages_origin",
        ),
        Index(
            "ix_ai_conversation_context_packages_conversation",
            "organization_id",
            "conversation_id",
            "created_at",
        ),
        Index("ix_ai_conversation_context_packages_hash", "context_hash"),
        {"schema": "ai"},
    )

    conversation_context_package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="organization", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_user_message: Mapped[str] = mapped_column(Text, nullable=False)
    included_turn_ids: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    excluded_turns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    context_window_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    context_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationRoutingConfiguration(Base):
    __tablename__ = "conversation_routing_configurations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "configuration_version",
            name="uq_ai_conversation_routing_configurations_org_version",
        ),
        UniqueConstraint(
            "routing_configuration_id",
            "organization_id",
            name="uq_ai_conversation_routing_configurations_id_organization",
        ),
        CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_routing_configurations_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_routing_configurations_origin",
        ),
        CheckConstraint(
            "configuration_status IN ('active','superseded','disabled')",
            name="ck_ai_conversation_routing_configurations_status",
        ),
        Index(
            "uq_ai_conversation_routing_configurations_active_org",
            "organization_id",
            unique=True,
            postgresql_where=text("configuration_status = 'active'"),
        ),
        Index("ix_ai_conversation_routing_configurations_hash", "configuration_hash"),
        {"schema": "ai"},
    )

    routing_configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="organization", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    configuration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_status: Mapped[str] = mapped_column(String(32), server_default="active", nullable=False)
    intent_catalog: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    provider_chain: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    confidence_thresholds: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    fallback_behavior: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    context_window_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    semantic_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationInteractionDecision(Base):
    __tablename__ = "conversation_interaction_decisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_interaction_decisions_org_turn",
        ),
        UniqueConstraint(
            "interaction_decision_id",
            "organization_id",
            "conversation_turn_id",
            name="uq_ai_conversation_interaction_decisions_id_organization_turn",
        ),
        ForeignKeyConstraint(
            ["conversation_turn_id", "conversation_id", "organization_id"],
            [
                "ai.conversation_turns.conversation_turn_id",
                "ai.conversation_turns.conversation_id",
                "ai.conversation_turns.organization_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_turn",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_context_package_id", "organization_id", "conversation_turn_id"],
            [
                "ai.conversation_context_packages.conversation_context_package_id",
                "ai.conversation_context_packages.organization_id",
                "ai.conversation_context_packages.conversation_turn_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_context",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["routing_configuration_id", "organization_id"],
            [
                "ai.conversation_routing_configurations.routing_configuration_id",
                "ai.conversation_routing_configurations.organization_id",
            ],
            name="fk_ai_conversation_interaction_decisions_scoped_configuration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["classification_evidence_id"],
            ["ai.conversation_intent_classification_evidence.classification_evidence_id"],
            name="fk_ai_conversation_interaction_decisions_classification",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "ownership_scope = 'organization' AND organization_id IS NOT NULL",
            name="ck_ai_conversation_interaction_decisions_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_interaction_decisions_origin",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_conversation_interaction_decisions_confidence",
        ),
        Index(
            "ix_ai_conversation_interaction_decisions_conversation",
            "organization_id",
            "conversation_id",
            "created_at",
        ),
        Index("ix_ai_conversation_interaction_decisions_intent", "intent", "created_at"),
        Index("ix_ai_conversation_interaction_decisions_input_hash", "input_hash"),
        Index("ix_ai_conversation_interaction_decisions_decision_hash", "decision_hash"),
        {"schema": "ai"},
    )

    interaction_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="organization", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="operational", nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_context_package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    routing_configuration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    classification_evidence_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    sub_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent_parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    referenced_turn_ids: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)
    conversation_context_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retrieval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    target_runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    slm_used: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    router_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assistant_session_id", "organization_id"],
            [
                "ai.assistant_sessions.assistant_session_id",
                "ai.assistant_sessions.organization_id",
            ],
            name="fk_ai_conversations_session_organization",
        ),
        CheckConstraint(
            "conversation_status IN ('active','completed','archived','blocked','failed','disabled')",
            name="ck_ai_conversations_status",
        ),
        Index("ix_ai_conversations_assistant", "assistant_id", "created_at"),
        Index("ix_ai_conversations_session", "assistant_session_id", "created_at"),
        Index("ix_ai_conversations_status", "conversation_status"),
        Index("ix_ai_conversations_reference", "conversation_reference"),
        Index("ix_ai_conversations_organization", "organization_id", "created_at"),
        Index("ix_ai_conversations_origin", "data_origin", "created_at"),
        UniqueConstraint("conversation_id", "organization_id", name="uq_ai_conversations_id_organization"),
        CheckConstraint(
            "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
            "(ownership_scope = 'legacy_unscoped' AND organization_id IS NULL)",
            name="ck_ai_conversations_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversations_origin",
        ),
        {"schema": "ai"},
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT")
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="legacy_unscoped", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="legacy", nullable=False)
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="SET NULL")
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    conversation_status: Mapped[str] = mapped_column(String(32), server_default="active", nullable=False)
    conversation_title: Mapped[str | None] = mapped_column(String(255))
    conversation_reference: Mapped[str | None] = mapped_column(String(255))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    runtime_context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    conversation_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_index", name="uq_ai_conversation_turns_conversation_index"),
        UniqueConstraint(
            "conversation_turn_id",
            "conversation_id",
            "organization_id",
            name="uq_ai_conversation_turns_id_conversation_organization",
        ),
        CheckConstraint("turn_index >= 0", name="ck_ai_conversation_turns_index"),
        CheckConstraint("turn_role IN ('user','assistant','system','tool')", name="ck_ai_conversation_turns_role"),
        CheckConstraint(
            "turn_status IN ('recorded','completed','blocked','failed','disabled')",
            name="ck_ai_conversation_turns_status",
        ),
        Index("ix_ai_conversation_turns_conversation", "conversation_id", "turn_index"),
        Index("ix_ai_conversation_turns_assistant", "assistant_id", "created_at"),
        Index("ix_ai_conversation_turns_assistant_run", "assistant_run_id"),
        Index("ix_ai_conversation_turns_response", "assistant_response_id"),
        Index(
            "uq_ai_conversation_turns_assistant_response",
            "conversation_id",
            "assistant_response_id",
            unique=True,
            postgresql_where=text("assistant_response_id IS NOT NULL"),
        ),
        Index(
            "uq_ai_conversation_turns_response_identity",
            "assistant_response_id",
            unique=True,
            postgresql_where=text("assistant_response_id IS NOT NULL"),
        ),
        Index(
            "uq_ai_conversation_turns_deterministic_operation",
            "deterministic_interaction_plan_id",
            unique=True,
            postgresql_where=text("deterministic_interaction_plan_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(deterministic_interaction_plan_id IS NULL AND deterministic_input_fingerprint IS NULL) OR "
            "(deterministic_interaction_plan_id IS NOT NULL AND deterministic_input_fingerprint IS NOT NULL "
            "AND turn_role = 'assistant' AND assistant_response_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_ai_conversation_turns_deterministic_identity",
        ),
        ForeignKeyConstraint(
            ["deterministic_interaction_plan_id", "organization_id", "conversation_id"],
            [
                "ai.conversation_interaction_plans.interaction_plan_id",
                "ai.conversation_interaction_plans.organization_id",
                "ai.conversation_interaction_plans.conversation_id",
            ],
            name="fk_ai_conversation_turns_deterministic_plan_lineage",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_conversation_turns_role", "turn_role"),
        Index("ix_ai_conversation_turns_status", "turn_status"),
        Index("ix_ai_conversation_turns_organization", "organization_id", "created_at"),
        Index("ix_ai_conversation_turns_origin", "data_origin", "created_at"),
        Index(
            "uq_ai_conversation_turns_chat_request",
            "organization_id",
            "assistant_id",
            "request_id",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL AND turn_role = 'user'"),
        ),
        ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["ai.conversations.conversation_id", "ai.conversations.organization_id"],
            name="fk_ai_conversation_turns_conversation_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(ownership_scope = 'organization' AND organization_id IS NOT NULL) OR "
            "(ownership_scope = 'legacy_unscoped' AND organization_id IS NULL)",
            name="ck_ai_conversation_turns_ownership",
        ),
        CheckConstraint(
            "data_origin IN ('operational','reference','validation','legacy')",
            name="ck_ai_conversation_turns_origin",
        ),
        {"schema": "ai"},
    )

    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.organizations.id", ondelete="RESTRICT")
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), server_default="legacy_unscoped", nullable=False)
    data_origin: Mapped[str] = mapped_column(String(32), server_default="legacy", nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.conversations.conversation_id", ondelete="CASCADE"), nullable=False
    )
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_definitions.assistant_id", ondelete="SET NULL")
    )
    assistant_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_sessions.assistant_session_id", ondelete="SET NULL")
    )
    assistant_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_runtime_runs.assistant_run_id", ondelete="SET NULL")
    )
    assistant_response_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.assistant_responses.assistant_response_id", ondelete="SET NULL")
    )
    request_id: Mapped[str | None] = mapped_column(String(128))
    deterministic_interaction_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deterministic_input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_role: Mapped[str] = mapped_column(String(32), nullable=False)
    turn_status: Mapped[str] = mapped_column(String(32), server_default="recorded", nullable=False)
    input_text: Mapped[str | None] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    response_format: Mapped[str] = mapped_column(String(64), server_default="markdown", nullable=False)
    citation_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    ordered_citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    turn_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
