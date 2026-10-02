from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantContextPackage,
    AssistantDefinition,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantResponse,
    AssistantRetrievalExecutionPlan,
    AssistantRetrievalPlan,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
    Conversation,
    ConversationContextPackage,
    ConversationInteractionDecision,
    ConversationRoutingConfiguration,
    ConversationTurn,
)
from app.models.core import Organization


class AssistantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _ownership_for_assistant(
        self,
        assistant_id: uuid.UUID,
        *,
        execution_organization_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        assistant = self.session.get(AssistantDefinition, assistant_id)
        if assistant is None or assistant.ownership_scope == "legacy_unscoped":
            raise ValueError("assistant ownership is unavailable")
        if assistant.ownership_scope == "organization":
            if execution_organization_id is not None and assistant.organization_id != execution_organization_id:
                raise ValueError("assistant organization is inconsistent with execution scope")
            organization_id = assistant.organization_id
            ownership_scope = "organization"
        elif execution_organization_id is not None:
            organization_id = execution_organization_id
            ownership_scope = "organization"
        else:
            organization_id = None
            ownership_scope = "global"
        return {
            "organization_id": organization_id,
            "ownership_scope": ownership_scope,
            "data_origin": assistant.data_origin,
        }

    @staticmethod
    def _apply_data_origin(ownership: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
        governed = dict(metadata or {})
        requested_origin = governed.get("data_origin")
        if governed.get("validation_generated") is True:
            requested_origin = "validation"
        if requested_origin in {"operational", "reference", "validation"}:
            return {**ownership, "data_origin": requested_origin}
        return ownership

    @staticmethod
    def _validate_parent_ownership(parent: Any, ownership: dict[str, Any], *, assistant_id: uuid.UUID) -> None:
        if getattr(parent, "assistant_id", assistant_id) != assistant_id:
            raise ValueError("assistant lineage is inconsistent")
        if ownership["ownership_scope"] == "global" and parent.ownership_scope == "organization":
            ownership["ownership_scope"] = "organization"
            ownership["organization_id"] = parent.organization_id
        else:
            if parent.ownership_scope != ownership["ownership_scope"]:
                raise ValueError("ownership lineage is inconsistent")
            if parent.organization_id != ownership["organization_id"]:
                raise ValueError("organization lineage is inconsistent")
        ownership["data_origin"] = parent.data_origin

    def _owned_artifact_statement(
        self,
        model: Any,
        identifier_column: Any,
        identifier: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool = False,
    ) -> Any:
        statement = select(model).where(identifier_column == identifier)
        if platform_scope:
            return statement.where(model.ownership_scope != "legacy_unscoped")
        return statement.where(
            or_(
                model.ownership_scope == "global",
                (model.ownership_scope == "organization") & (model.organization_id == organization_id),
            )
        )

    def get_scoped_artifact(
        self,
        model: Any,
        identifier_column: Any,
        identifier: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool = False,
    ) -> Any | None:
        return self.session.scalar(
            self._owned_artifact_statement(
                model,
                identifier_column,
                identifier,
                organization_id=organization_id,
                platform_scope=platform_scope,
            )
        )

    def create_assistant_definition(
        self,
        *,
        assistant_key: str,
        assistant_name: str,
        assistant_status: str = "prepared",
        assistant_version: str = "1.0",
        assistant_type: str = "platform_assistant",
        description: str | None = None,
        default_search_mode: str = "enterprise_search",
        allowed_runtime_domains: list[str] | None = None,
        guardrail_profile: dict[str, Any] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None,
        ownership_scope: str,
        data_origin: str,
    ) -> tuple[AssistantDefinition, bool]:
        statement = select(AssistantDefinition).where(
            AssistantDefinition.assistant_key == assistant_key,
            AssistantDefinition.assistant_version == assistant_version,
            AssistantDefinition.ownership_scope == ownership_scope,
        )
        if ownership_scope == "organization":
            statement = statement.where(AssistantDefinition.organization_id == organization_id)
        else:
            statement = statement.where(AssistantDefinition.organization_id.is_(None))
        existing = self.session.scalar(statement)
        if existing is not None:
            existing.assistant_name = assistant_name
            existing.assistant_status = assistant_status
            existing.assistant_type = assistant_type
            existing.description = description
            existing.default_search_mode = default_search_mode
            existing.allowed_runtime_domains = list(allowed_runtime_domains or [])
            existing.guardrail_profile = dict(guardrail_profile or {})
            existing.runtime_metadata = {**(existing.runtime_metadata or {}), **dict(runtime_metadata or {})}
            existing.data_origin = data_origin
            self.session.add(existing)
            self.session.flush()
            return existing, False
        record = AssistantDefinition(
            organization_id=organization_id,
            ownership_scope=ownership_scope,
            data_origin=data_origin,
            assistant_key=assistant_key,
            assistant_name=assistant_name,
            assistant_status=assistant_status,
            assistant_version=assistant_version,
            assistant_type=assistant_type,
            description=description,
            default_search_mode=default_search_mode,
            allowed_runtime_domains=list(allowed_runtime_domains or []),
            guardrail_profile=dict(guardrail_profile or {}),
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def get_assistant_definition(self, assistant_id: uuid.UUID) -> AssistantDefinition | None:
        return self.session.get(AssistantDefinition, assistant_id)

    def get_scoped_assistant_definition(
        self,
        assistant_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool = False,
    ) -> AssistantDefinition | None:
        statement = select(AssistantDefinition).where(AssistantDefinition.assistant_id == assistant_id)
        if platform_scope:
            statement = statement.where(AssistantDefinition.ownership_scope != "legacy_unscoped")
        else:
            statement = statement.where(
                or_(
                    AssistantDefinition.ownership_scope == "global",
                    (
                        (AssistantDefinition.ownership_scope == "organization")
                        & (AssistantDefinition.organization_id == organization_id)
                    ),
                )
            )
        return self.session.scalar(statement)

    def list_scoped_assistant_definitions(
        self,
        *,
        organization_id: uuid.UUID | None,
        platform_scope: bool = False,
        assistant_status: str | None = None,
        limit: int = 100,
    ) -> list[AssistantDefinition]:
        statement = select(AssistantDefinition)
        if platform_scope:
            statement = statement.where(AssistantDefinition.ownership_scope != "legacy_unscoped")
        else:
            statement = statement.where(
                or_(
                    AssistantDefinition.ownership_scope == "global",
                    (
                        (AssistantDefinition.ownership_scope == "organization")
                        & (AssistantDefinition.organization_id == organization_id)
                    ),
                )
            )
        if assistant_status:
            statement = statement.where(AssistantDefinition.assistant_status == assistant_status)
        statement = statement.order_by(AssistantDefinition.created_at.desc()).limit(max(1, min(limit, 500)))
        return list(self.session.scalars(statement).all())

    def list_assistant_definitions(
        self, *, assistant_status: str | None = None, limit: int = 100
    ) -> list[AssistantDefinition]:
        statement = select(AssistantDefinition)
        if assistant_status:
            statement = statement.where(AssistantDefinition.assistant_status == assistant_status)
        statement = statement.order_by(
            AssistantDefinition.created_at.desc(), AssistantDefinition.assistant_id.asc()
        ).limit(max(1, min(int(limit), 500)))
        return list(self.session.scalars(statement).all())

    def create_assistant_session(
        self,
        *,
        assistant_id: uuid.UUID,
        execution_organization_id: uuid.UUID | None = None,
        session_status: str = "prepared",
        requested_by: str | None = None,
        conversation_reference: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AssistantSession:
        assistant = self.session.get(AssistantDefinition, assistant_id)
        if assistant is None:
            raise ValueError("assistant ownership is unavailable")
        if assistant.ownership_scope == "global" and execution_organization_id is not None:
            raise ValueError("global assistant cannot be promoted to organization session")
        ownership = self._apply_data_origin(
            self._ownership_for_assistant(
                assistant_id,
                execution_organization_id=execution_organization_id,
            ),
            runtime_context,
        )
        record = AssistantSession(
            **ownership,
            assistant_id=assistant_id,
            session_status=session_status,
            requested_by=requested_by,
            conversation_reference=conversation_reference,
            runtime_context=dict(runtime_context or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_session(self, assistant_session_id: uuid.UUID) -> AssistantSession | None:
        return self.session.get(AssistantSession, assistant_session_id)

    def get_scoped_assistant_session(
        self,
        assistant_session_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
    ) -> AssistantSession | None:
        return self.session.scalar(
            select(AssistantSession).where(
                AssistantSession.assistant_session_id == assistant_session_id,
                AssistantSession.organization_id == organization_id,
                AssistantSession.ownership_scope == "organization",
            )
        )

    def assistant_session_exists(self, assistant_session_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(AssistantSession.assistant_session_id).where(
                    AssistantSession.assistant_session_id == assistant_session_id
                )
            )
            is not None
        )

    def _session_for_ownership(
        self, assistant_session_id: uuid.UUID, ownership: dict[str, Any]
    ) -> AssistantSession | None:
        if ownership["ownership_scope"] == "organization":
            return self.get_scoped_assistant_session(assistant_session_id, organization_id=ownership["organization_id"])
        if ownership["ownership_scope"] == "global":
            return self.session.scalar(
                select(AssistantSession).where(
                    AssistantSession.assistant_session_id == assistant_session_id,
                    AssistantSession.ownership_scope == "global",
                    AssistantSession.organization_id.is_(None),
                )
            )
        return None

    def _require_conversation_session(
        self,
        *,
        assistant_session_id: uuid.UUID,
        organization_id: uuid.UUID,
        assistant_id: uuid.UUID | None,
    ) -> AssistantSession:
        session = self.get_scoped_assistant_session(
            assistant_session_id,
            organization_id=organization_id,
        )
        if session is None:
            if not self.assistant_session_exists(assistant_session_id):
                raise ValueError("assistant_session_not_found")
            raise ValueError("assistant_session_not_authorized_for_organization")
        if assistant_id is not None and session.assistant_id != assistant_id:
            raise ValueError("assistant_session_assistant_mismatch")
        return session

    def create_assistant_runtime_run(
        self,
        *,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
        run_status: str = "planned",
        requested_query: str | None = None,
        selected_search_mode: str = "enterprise_search",
        selected_runtime_domain: str = "enterprise_search",
        execution_state: str = "metadata_only",
        runtime_metadata: dict[str, Any] | None = None,
        execution_organization_id: uuid.UUID | None = None,
    ) -> AssistantRuntimeRun:
        ownership = self._apply_data_origin(
            self._ownership_for_assistant(assistant_id, execution_organization_id=execution_organization_id),
            runtime_metadata,
        )
        parent = self._session_for_ownership(assistant_session_id, ownership)
        if parent is None:
            raise ValueError("assistant session not found")
        self._validate_parent_ownership(parent, ownership, assistant_id=assistant_id)
        record = AssistantRuntimeRun(
            **ownership,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            run_status=run_status,
            requested_query=requested_query,
            selected_search_mode=selected_search_mode,
            selected_runtime_domain=selected_runtime_domain,
            execution_state=execution_state,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_runtime_run(self, assistant_run_id: uuid.UUID) -> AssistantRuntimeRun | None:
        return self.session.get(AssistantRuntimeRun, assistant_run_id)

    def create_assistant_retrieval_plan(
        self,
        *,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        plan_status: str = "planned",
        requested_query: str | None = None,
        selected_search_mode: str = "enterprise_search",
        selected_runtime_domain: str = "enterprise_search",
        execution_state: str = "metadata_only",
        enterprise_search_planned: bool = True,
        semantic_search_planned: bool = False,
        hybrid_search_planned: bool = False,
        retrieval_executed: bool = False,
        runtime_metadata: dict[str, Any] | None = None,
        execution_organization_id: uuid.UUID | None = None,
    ) -> AssistantRetrievalPlan:
        ownership = self._apply_data_origin(
            self._ownership_for_assistant(assistant_id, execution_organization_id=execution_organization_id),
            runtime_metadata,
        )
        if assistant_session_id is not None:
            parent = self._session_for_ownership(assistant_session_id, ownership)
            if parent is None:
                raise ValueError("assistant session not found")
            self._validate_parent_ownership(parent, ownership, assistant_id=assistant_id)
        record = AssistantRetrievalPlan(
            **ownership,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            plan_status=plan_status,
            requested_query=requested_query,
            selected_search_mode=selected_search_mode,
            selected_runtime_domain=selected_runtime_domain,
            execution_state=execution_state,
            enterprise_search_planned=enterprise_search_planned,
            semantic_search_planned=semantic_search_planned,
            hybrid_search_planned=hybrid_search_planned,
            retrieval_executed=retrieval_executed,
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_retrieval_plan(self, retrieval_plan_id: uuid.UUID) -> AssistantRetrievalPlan | None:
        return self.session.get(AssistantRetrievalPlan, retrieval_plan_id)

    def create_assistant_retrieval_execution_plan(
        self,
        *,
        retrieval_plan_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        execution_status: str = "prepared",
        selected_search_mode: str = "enterprise_search",
        selected_runtime_domain: str = "enterprise_search",
        execution_state: str = "readiness_only",
        enterprise_search_execution_prepared: bool = True,
        semantic_search_execution_prepared: bool = False,
        hybrid_search_execution_prepared: bool = False,
        retrieval_executed: bool = False,
        answer_generated: bool = False,
        llm_used: bool = False,
        tool_called: bool = False,
        workflow_executed: bool = False,
        external_action_called: bool = False,
        autonomous_execution: bool = False,
        readiness_metadata: dict[str, Any] | None = None,
    ) -> AssistantRetrievalExecutionPlan:
        ownership = self._apply_data_origin(self._ownership_for_assistant(assistant_id), readiness_metadata)
        parent = self.session.get(AssistantRetrievalPlan, retrieval_plan_id)
        if parent is None:
            raise ValueError("retrieval plan not found")
        self._validate_parent_ownership(parent, ownership, assistant_id=assistant_id)
        if parent.assistant_session_id != assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        record = AssistantRetrievalExecutionPlan(
            **ownership,
            retrieval_plan_id=retrieval_plan_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            execution_status=execution_status,
            selected_search_mode=selected_search_mode,
            selected_runtime_domain=selected_runtime_domain,
            execution_state=execution_state,
            enterprise_search_execution_prepared=enterprise_search_execution_prepared,
            semantic_search_execution_prepared=semantic_search_execution_prepared,
            hybrid_search_execution_prepared=hybrid_search_execution_prepared,
            retrieval_executed=retrieval_executed,
            answer_generated=answer_generated,
            llm_used=llm_used,
            tool_called=tool_called,
            workflow_executed=workflow_executed,
            external_action_called=external_action_called,
            autonomous_execution=autonomous_execution,
            readiness_metadata=dict(readiness_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_retrieval_execution_plan(
        self, execution_plan_id: uuid.UUID
    ) -> AssistantRetrievalExecutionPlan | None:
        return self.session.get(AssistantRetrievalExecutionPlan, execution_plan_id)

    def list_assistant_retrieval_execution_plans(
        self,
        *,
        retrieval_plan_id: uuid.UUID,
        limit: int = 100,
    ) -> list[AssistantRetrievalExecutionPlan]:
        statement = (
            select(AssistantRetrievalExecutionPlan)
            .where(AssistantRetrievalExecutionPlan.retrieval_plan_id == retrieval_plan_id)
            .order_by(
                AssistantRetrievalExecutionPlan.created_at.desc(),
                AssistantRetrievalExecutionPlan.execution_plan_id.asc(),
            )
            .limit(max(1, min(int(limit), 500)))
        )
        return list(self.session.scalars(statement).all())

    def create_assistant_search_execution(
        self,
        *,
        execution_plan_id: uuid.UUID,
        retrieval_plan_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        search_mode: str = "enterprise_search",
        runtime_domain: str = "enterprise_search",
        search_query: str,
        search_completed: bool,
        search_duration_ms: int | None = None,
        result_count: int = 0,
        lexical_search_used: bool = True,
        postgresql_fts_used: bool = True,
        semantic_search_used: bool = False,
        hybrid_search_used: bool = False,
        qdrant_used: bool = False,
        reranking_used: bool = False,
        llm_used: bool = False,
        answer_generated: bool = False,
        tool_called: bool = False,
        workflow_executed: bool = False,
        external_action_called: bool = False,
        autonomous_execution: bool = False,
        execution_metadata: dict[str, Any] | None = None,
    ) -> AssistantSearchExecution:
        ownership = self._apply_data_origin(self._ownership_for_assistant(assistant_id), execution_metadata)
        parent = self.session.get(AssistantRetrievalExecutionPlan, execution_plan_id)
        if parent is None:
            raise ValueError("retrieval execution plan not found")
        self._validate_parent_ownership(parent, ownership, assistant_id=assistant_id)
        if parent.retrieval_plan_id != retrieval_plan_id:
            raise ValueError("retrieval lineage is inconsistent")
        if parent.assistant_session_id != assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        record = AssistantSearchExecution(
            **ownership,
            execution_plan_id=execution_plan_id,
            retrieval_plan_id=retrieval_plan_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            search_mode=search_mode,
            runtime_domain=runtime_domain,
            search_query=search_query,
            search_completed=search_completed,
            search_duration_ms=search_duration_ms,
            result_count=max(0, int(result_count or 0)),
            lexical_search_used=lexical_search_used,
            postgresql_fts_used=postgresql_fts_used,
            semantic_search_used=semantic_search_used,
            hybrid_search_used=hybrid_search_used,
            qdrant_used=qdrant_used,
            reranking_used=reranking_used,
            llm_used=llm_used,
            answer_generated=answer_generated,
            tool_called=tool_called,
            workflow_executed=workflow_executed,
            external_action_called=external_action_called,
            autonomous_execution=autonomous_execution,
            execution_metadata=dict(execution_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_search_execution(self, search_execution_id: uuid.UUID) -> AssistantSearchExecution | None:
        return self.session.get(AssistantSearchExecution, search_execution_id)

    def create_context_package(
        self,
        *,
        search_execution_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        package_status: str = "created",
        chunk_count: int = 0,
        citation_count: int = 0,
        total_tokens_estimated: int = 0,
        context_size_bytes: int = 0,
        truncation_required: bool = False,
        truncation_applied: bool = False,
        ordered_context: list[dict[str, Any]] | None = None,
        ordered_citations: list[dict[str, Any]] | None = None,
        package_metadata: dict[str, Any] | None = None,
    ) -> AssistantContextPackage:
        parent = self.session.get(AssistantSearchExecution, search_execution_id)
        if parent is None:
            raise ValueError("search execution not found")
        ownership = {
            "organization_id": parent.organization_id,
            "ownership_scope": parent.ownership_scope,
            "data_origin": parent.data_origin,
        }
        if parent.assistant_id != assistant_id:
            raise ValueError("assistant lineage is inconsistent")
        if assistant_session_id is not None and assistant_session_id != parent.assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        assistant_session_id = parent.assistant_session_id
        record = AssistantContextPackage(
            **ownership,
            search_execution_id=search_execution_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            package_status=package_status,
            chunk_count=max(0, int(chunk_count or 0)),
            citation_count=max(0, int(citation_count or 0)),
            total_tokens_estimated=max(0, int(total_tokens_estimated or 0)),
            context_size_bytes=max(0, int(context_size_bytes or 0)),
            truncation_required=truncation_required,
            truncation_applied=truncation_applied,
            ordered_context=list(ordered_context or []),
            ordered_citations=list(ordered_citations or []),
            package_metadata=dict(package_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_context_package(self, context_package_id: uuid.UUID) -> AssistantContextPackage | None:
        return self.session.get(AssistantContextPackage, context_package_id)

    def create_prompt_package(
        self,
        *,
        context_package_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        package_status: str = "created",
        system_prompt: str,
        assistant_instructions: str,
        assembled_context: str,
        citation_section: str,
        estimated_prompt_tokens: int = 0,
        prompt_size_bytes: int = 0,
        prompt_metadata: dict[str, Any] | None = None,
        llm_ready: bool = True,
        llm_invoked: bool = False,
        answer_generated: bool = False,
    ) -> AssistantPromptPackage:
        parent = self.session.get(AssistantContextPackage, context_package_id)
        if parent is None:
            raise ValueError("context package not found")
        ownership = {
            "organization_id": parent.organization_id,
            "ownership_scope": parent.ownership_scope,
            "data_origin": parent.data_origin,
        }
        if parent.assistant_id != assistant_id:
            raise ValueError("assistant lineage is inconsistent")
        if assistant_session_id is not None and assistant_session_id != parent.assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        assistant_session_id = parent.assistant_session_id
        record = AssistantPromptPackage(
            **ownership,
            context_package_id=context_package_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            package_status=package_status,
            system_prompt=system_prompt,
            assistant_instructions=assistant_instructions,
            assembled_context=assembled_context,
            citation_section=citation_section,
            estimated_prompt_tokens=max(0, int(estimated_prompt_tokens or 0)),
            prompt_size_bytes=max(0, int(prompt_size_bytes or 0)),
            prompt_metadata=dict(prompt_metadata or {}),
            llm_ready=llm_ready,
            llm_invoked=llm_invoked,
            answer_generated=answer_generated,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_prompt_package(self, prompt_package_id: uuid.UUID) -> AssistantPromptPackage | None:
        return self.session.get(AssistantPromptPackage, prompt_package_id)

    def create_llm_invocation_plan(
        self,
        *,
        prompt_package_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        provider_type: str = "reference",
        provider_name: str = "metadata-only",
        model_name: str = "metadata-only",
        provider_ready: bool = True,
        execution_allowed: bool = False,
        blocked_reason: str = "execution_disabled",
        planned_temperature: float = 0.0,
        planned_max_tokens: int = 1024,
        planned_top_p: float = 1.0,
        planned_stop_sequences: list[str] | None = None,
        planned_seed: int | None = None,
        planned_timeout: int = 30,
        llm_invoked: bool = False,
        answer_generated: bool = False,
        tool_execution: bool = False,
        workflow_execution: bool = False,
        external_action_called: bool = False,
        autonomous_execution: bool = False,
        gateway_metadata: dict[str, Any] | None = None,
    ) -> AssistantLlmInvocationPlan:
        parent = self.session.get(AssistantPromptPackage, prompt_package_id)
        if parent is None:
            raise ValueError("prompt package not found")
        ownership = {
            "organization_id": parent.organization_id,
            "ownership_scope": parent.ownership_scope,
            "data_origin": parent.data_origin,
        }
        if parent.assistant_id != assistant_id:
            raise ValueError("assistant lineage is inconsistent")
        if assistant_session_id is not None and assistant_session_id != parent.assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        assistant_session_id = parent.assistant_session_id
        record = AssistantLlmInvocationPlan(
            **ownership,
            prompt_package_id=prompt_package_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            provider_type=provider_type,
            provider_name=provider_name,
            model_name=model_name,
            provider_ready=provider_ready,
            execution_allowed=execution_allowed,
            blocked_reason=blocked_reason,
            planned_temperature=max(0.0, float(planned_temperature or 0.0)),
            planned_max_tokens=max(1, int(planned_max_tokens or 1)),
            planned_top_p=max(0.0, min(1.0, float(planned_top_p if planned_top_p is not None else 1.0))),
            planned_stop_sequences=list(planned_stop_sequences or []),
            planned_seed=planned_seed,
            planned_timeout=max(1, int(planned_timeout or 1)),
            llm_invoked=llm_invoked,
            answer_generated=answer_generated,
            tool_execution=tool_execution,
            workflow_execution=workflow_execution,
            external_action_called=external_action_called,
            autonomous_execution=autonomous_execution,
            gateway_metadata=dict(gateway_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_llm_invocation_plan(self, gateway_id: uuid.UUID) -> AssistantLlmInvocationPlan | None:
        return self.session.get(AssistantLlmInvocationPlan, gateway_id)

    def create_llm_execution(
        self,
        *,
        gateway_id: uuid.UUID,
        prompt_package_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        provider_type: str = "local_mock",
        provider_name: str = "deterministic-local-mock",
        model_name: str = "deterministic-assistant-runtime-mock",
        execution_status: str = "completed",
        execution_allowed: bool = True,
        provider_called: bool = True,
        provider_call_mode: str = "deterministic_local_mock",
        request_payload_metadata: dict[str, Any] | None = None,
        raw_output_text: str | None = None,
        raw_output_metadata: dict[str, Any] | None = None,
        prompt_tokens_estimated: int = 0,
        completion_tokens_estimated: int = 0,
        total_tokens_estimated: int = 0,
        latency_ms: int | None = None,
        cost_metadata: dict[str, Any] | None = None,
        citation_verification_completed: bool = False,
        final_response_created: bool = False,
        tool_called: bool = False,
        workflow_executed: bool = False,
        external_action_called: bool = False,
        autonomous_execution: bool = False,
    ) -> AssistantLlmExecution:
        parent = self.session.get(AssistantLlmInvocationPlan, gateway_id)
        if parent is None:
            raise ValueError("LLM invocation plan not found")
        ownership = {
            "organization_id": parent.organization_id,
            "ownership_scope": parent.ownership_scope,
            "data_origin": parent.data_origin,
        }
        if parent.assistant_id != assistant_id:
            raise ValueError("assistant lineage is inconsistent")
        if assistant_session_id is not None and assistant_session_id != parent.assistant_session_id:
            raise ValueError("assistant session lineage is inconsistent")
        assistant_session_id = parent.assistant_session_id
        if parent.prompt_package_id != prompt_package_id:
            raise ValueError("prompt lineage is inconsistent")
        record = AssistantLlmExecution(
            **ownership,
            gateway_id=gateway_id,
            prompt_package_id=prompt_package_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            provider_type=provider_type,
            provider_name=provider_name,
            model_name=model_name,
            execution_status=execution_status,
            execution_allowed=execution_allowed,
            provider_called=provider_called,
            provider_call_mode=provider_call_mode,
            request_payload_metadata=dict(request_payload_metadata or {}),
            raw_output_text=raw_output_text,
            raw_output_metadata=dict(raw_output_metadata or {}),
            prompt_tokens_estimated=max(0, int(prompt_tokens_estimated or 0)),
            completion_tokens_estimated=max(0, int(completion_tokens_estimated or 0)),
            total_tokens_estimated=max(0, int(total_tokens_estimated or 0)),
            latency_ms=max(0, int(latency_ms)) if latency_ms is not None else None,
            cost_metadata=dict(cost_metadata or {}),
            citation_verification_completed=citation_verification_completed,
            final_response_created=final_response_created,
            tool_called=tool_called,
            workflow_executed=workflow_executed,
            external_action_called=external_action_called,
            autonomous_execution=autonomous_execution,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_llm_executions_for_plan(self, gateway_id: uuid.UUID) -> list[AssistantLlmExecution]:
        statement = (
            select(AssistantLlmExecution)
            .where(AssistantLlmExecution.gateway_id == gateway_id)
            .order_by(AssistantLlmExecution.created_at.asc(), AssistantLlmExecution.llm_execution_id.asc())
            .limit(2)
        )
        return list(self.session.scalars(statement).all())

    def get_llm_execution(self, llm_execution_id: uuid.UUID) -> AssistantLlmExecution | None:
        return self.session.get(AssistantLlmExecution, llm_execution_id)

    def mark_llm_execution_citation_verified(self, llm_execution_id: uuid.UUID) -> AssistantLlmExecution | None:
        record = self.get_llm_execution(llm_execution_id)
        if record is None:
            return None
        record.citation_verification_completed = True
        self.session.add(record)
        self.session.flush()
        return record

    def create_citation_verification(
        self,
        *,
        llm_execution_id: uuid.UUID,
        prompt_package_id: uuid.UUID,
        context_package_id: uuid.UUID,
        assistant_runtime_id: uuid.UUID | None = None,
        verification_status: str = "completed",
        verified_citation_count: int = 0,
        missing_citation_count: int = 0,
        invalid_citation_count: int = 0,
        verification_summary: dict[str, Any] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> AssistantCitationVerification:
        execution = self.session.get(AssistantLlmExecution, llm_execution_id)
        prompt = self.session.get(AssistantPromptPackage, prompt_package_id)
        context = self.session.get(AssistantContextPackage, context_package_id)
        if execution is None or prompt is None or context is None:
            raise ValueError("citation lineage is incomplete")
        if execution.prompt_package_id != prompt_package_id or prompt.context_package_id != context_package_id:
            raise ValueError("citation lineage is inconsistent")
        ownership = {
            "organization_id": execution.organization_id,
            "ownership_scope": execution.ownership_scope,
            "data_origin": execution.data_origin,
        }
        ownership = self._apply_data_origin(ownership, runtime_metadata)
        if any(
            artifact.assistant_id != execution.assistant_id
            or artifact.organization_id != execution.organization_id
            or artifact.ownership_scope != execution.ownership_scope
            for artifact in (prompt, context)
        ):
            raise ValueError("citation ownership lineage is inconsistent")
        if (
            prompt.assistant_session_id != execution.assistant_session_id
            or context.assistant_session_id != execution.assistant_session_id
        ):
            raise ValueError("citation assistant session lineage is inconsistent")
        record = AssistantCitationVerification(
            **ownership,
            assistant_runtime_id=assistant_runtime_id,
            llm_execution_id=llm_execution_id,
            prompt_package_id=prompt_package_id,
            context_package_id=context_package_id,
            verification_status=verification_status,
            verified_citation_count=max(0, int(verified_citation_count or 0)),
            missing_citation_count=max(0, int(missing_citation_count or 0)),
            invalid_citation_count=max(0, int(invalid_citation_count or 0)),
            verification_summary=dict(verification_summary or {}),
            runtime_metadata=dict(runtime_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_citation_verification(self, citation_verification_id: uuid.UUID) -> AssistantCitationVerification | None:
        return self.session.get(AssistantCitationVerification, citation_verification_id)

    def create_assistant_response(
        self,
        *,
        citation_verification_id: uuid.UUID,
        llm_execution_id: uuid.UUID,
        prompt_package_id: uuid.UUID,
        context_package_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID | None = None,
        response_status: str = "completed",
        response_text: str,
        response_format: str = "markdown",
        response_language: str = "unknown",
        citation_verification_passed: bool = True,
        verified_citation_count: int = 0,
        missing_citation_count: int = 0,
        invalid_citation_count: int = 0,
        ordered_citations: list[dict[str, Any]] | None = None,
        response_metadata: dict[str, Any] | None = None,
    ) -> AssistantResponse:
        parent = self.session.get(AssistantCitationVerification, citation_verification_id)
        if parent is None:
            raise ValueError("citation verification not found")
        ownership = {
            "organization_id": parent.organization_id,
            "ownership_scope": parent.ownership_scope,
            "data_origin": parent.data_origin,
        }
        if (
            parent.llm_execution_id != llm_execution_id
            or parent.prompt_package_id != prompt_package_id
            or parent.context_package_id != context_package_id
        ):
            raise ValueError("response lineage is inconsistent")
        execution = self.session.get(AssistantLlmExecution, llm_execution_id)
        if execution is None or execution.assistant_id != assistant_id:
            raise ValueError("response assistant lineage is inconsistent")
        prompt = self.session.get(AssistantPromptPackage, prompt_package_id)
        context = self.session.get(AssistantContextPackage, context_package_id)
        if prompt is None or context is None:
            raise ValueError("response lineage is incomplete")
        if any(
            artifact.assistant_id != execution.assistant_id
            or artifact.organization_id != execution.organization_id
            or artifact.ownership_scope != execution.ownership_scope
            for artifact in (prompt, context)
        ) or (
            execution.organization_id != ownership["organization_id"]
            or execution.ownership_scope != ownership["ownership_scope"]
        ):
            raise ValueError("response ownership lineage is inconsistent")
        if (
            assistant_session_id != execution.assistant_session_id
            or prompt.assistant_session_id != execution.assistant_session_id
            or context.assistant_session_id != execution.assistant_session_id
        ):
            raise ValueError("response assistant session lineage is inconsistent")
        record = AssistantResponse(
            **ownership,
            citation_verification_id=citation_verification_id,
            llm_execution_id=llm_execution_id,
            prompt_package_id=prompt_package_id,
            context_package_id=context_package_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            response_status=response_status,
            response_text=response_text,
            response_format=response_format,
            response_language=response_language,
            citation_verification_passed=citation_verification_passed,
            verified_citation_count=max(0, int(verified_citation_count or 0)),
            missing_citation_count=max(0, int(missing_citation_count or 0)),
            invalid_citation_count=max(0, int(invalid_citation_count or 0)),
            ordered_citations=list(ordered_citations or []),
            response_metadata=dict(response_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_assistant_response(self, assistant_response_id: uuid.UUID) -> AssistantResponse | None:
        return self.session.get(AssistantResponse, assistant_response_id)

    def list_assistant_responses_by_citation_verification(
        self,
        *,
        citation_verification_id: uuid.UUID,
        limit: int = 100,
    ) -> list[AssistantResponse]:
        statement = (
            select(AssistantResponse)
            .where(AssistantResponse.citation_verification_id == citation_verification_id)
            .order_by(AssistantResponse.created_at.desc(), AssistantResponse.assistant_response_id.asc())
            .limit(max(1, min(int(limit), 500)))
        )
        return list(self.session.scalars(statement).all())

    def list_scoped_citation_verifications_for_run(
        self,
        *,
        assistant_run_id: uuid.UUID,
        organization_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
    ) -> list[AssistantCitationVerification]:
        statement = (
            select(AssistantCitationVerification)
            .join(
                AssistantLlmExecution,
                AssistantCitationVerification.llm_execution_id == AssistantLlmExecution.llm_execution_id,
            )
            .where(
                AssistantCitationVerification.assistant_runtime_id == assistant_run_id,
                AssistantCitationVerification.organization_id == organization_id,
                AssistantCitationVerification.ownership_scope == "organization",
                AssistantLlmExecution.organization_id == organization_id,
                AssistantLlmExecution.assistant_id == assistant_id,
                AssistantLlmExecution.assistant_session_id == assistant_session_id,
            )
            .order_by(
                AssistantCitationVerification.created_at.asc(),
                AssistantCitationVerification.citation_verification_id.asc(),
            )
            .limit(2)
        )
        return list(self.session.scalars(statement).all())

    def list_scoped_llm_executions_for_run(
        self,
        *,
        assistant_run_id: uuid.UUID,
        conversation_id: uuid.UUID,
        organization_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
    ) -> list[AssistantLlmExecution]:
        statement = (
            select(AssistantLlmExecution)
            .where(
                AssistantLlmExecution.organization_id == organization_id,
                AssistantLlmExecution.ownership_scope == "organization",
                AssistantLlmExecution.assistant_id == assistant_id,
                AssistantLlmExecution.assistant_session_id == assistant_session_id,
                AssistantLlmExecution.request_payload_metadata["assistant_run_id"].astext == str(assistant_run_id),
                AssistantLlmExecution.request_payload_metadata["conversation_id"].astext == str(conversation_id),
            )
            .order_by(
                AssistantLlmExecution.created_at.asc(),
                AssistantLlmExecution.llm_execution_id.asc(),
            )
            .limit(2)
        )
        return list(self.session.scalars(statement).all())

    def list_citation_verifications_by_llm_execution(
        self, llm_execution_id: uuid.UUID
    ) -> list[AssistantCitationVerification]:
        statement = (
            select(AssistantCitationVerification)
            .where(AssistantCitationVerification.llm_execution_id == llm_execution_id)
            .order_by(
                AssistantCitationVerification.created_at.asc(),
                AssistantCitationVerification.citation_verification_id.asc(),
            )
            .limit(2)
        )
        return list(self.session.scalars(statement).all())

    def list_scoped_assistant_responses_for_run(
        self,
        *,
        assistant_run_id: uuid.UUID,
        organization_id: uuid.UUID,
        assistant_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
    ) -> list[AssistantResponse]:
        statement = (
            select(AssistantResponse)
            .join(
                AssistantCitationVerification,
                AssistantResponse.citation_verification_id == AssistantCitationVerification.citation_verification_id,
            )
            .where(
                AssistantCitationVerification.assistant_runtime_id == assistant_run_id,
                AssistantCitationVerification.organization_id == organization_id,
                AssistantCitationVerification.ownership_scope == "organization",
                AssistantResponse.organization_id == organization_id,
                AssistantResponse.ownership_scope == "organization",
                AssistantResponse.assistant_id == assistant_id,
                AssistantResponse.assistant_session_id == assistant_session_id,
            )
            .order_by(AssistantResponse.created_at.asc(), AssistantResponse.assistant_response_id.asc())
            .limit(2)
        )
        return list(self.session.scalars(statement).all())

    def mark_llm_execution_final_response_created(self, llm_execution_id: uuid.UUID) -> AssistantLlmExecution | None:
        record = self.get_llm_execution(llm_execution_id)
        if record is None:
            return None
        record.final_response_created = True
        self.session.add(record)
        self.session.flush()
        return record

    def mark_prompt_package_answer_generated(self, prompt_package_id: uuid.UUID) -> AssistantPromptPackage | None:
        record = self.get_prompt_package(prompt_package_id)
        if record is None:
            return None
        record.answer_generated = True
        self.session.add(record)
        self.session.flush()
        return record

    def create_conversation_context_package(
        self,
        *,
        organization_id: uuid.UUID,
        data_origin: str,
        conversation_id: uuid.UUID,
        conversation_turn_id: uuid.UUID,
        current_user_message: str,
        included_turn_ids: list[str],
        excluded_turns: list[dict[str, Any]],
        context_window_policy: dict[str, Any],
        context_policy_version: str,
        context_hash: str,
        retrieval_inputs: dict[str, Any],
    ) -> ConversationContextPackage:
        record = ConversationContextPackage(
            organization_id=organization_id,
            ownership_scope="organization",
            data_origin=data_origin,
            conversation_id=conversation_id,
            conversation_turn_id=conversation_turn_id,
            current_user_message=current_user_message,
            included_turn_ids=list(included_turn_ids),
            excluded_turns=list(excluded_turns),
            context_window_policy=dict(context_window_policy),
            context_policy_version=context_policy_version,
            context_hash=context_hash,
            retrieval_inputs=dict(retrieval_inputs),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_scoped_conversation_context_package(
        self, *, conversation_turn_id: uuid.UUID, organization_id: uuid.UUID
    ) -> ConversationContextPackage | None:
        return self.session.scalar(
            select(ConversationContextPackage).where(
                ConversationContextPackage.conversation_turn_id == conversation_turn_id,
                ConversationContextPackage.organization_id == organization_id,
                ConversationContextPackage.ownership_scope == "organization",
            )
        )

    def get_scoped_conversation_turn(
        self, conversation_turn_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> ConversationTurn | None:
        return self.session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_turn_id == conversation_turn_id,
                ConversationTurn.organization_id == organization_id,
                ConversationTurn.ownership_scope == "organization",
            )
        )

    def list_scoped_conversation_turns_before(
        self,
        *,
        conversation_id: uuid.UUID,
        conversation_turn_index: int,
        organization_id: uuid.UUID,
    ) -> list[ConversationTurn]:
        statement = (
            select(ConversationTurn)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.organization_id == organization_id,
                ConversationTurn.ownership_scope == "organization",
                ConversationTurn.turn_index < conversation_turn_index,
            )
            .order_by(
                ConversationTurn.turn_index.asc(),
                ConversationTurn.created_at.asc(),
                ConversationTurn.conversation_turn_id.asc(),
            )
        )
        return list(self.session.scalars(statement).all())

    def lock_conversation_routing_configuration_scope(self, *, organization_id: uuid.UUID) -> Organization | None:
        return self.session.scalar(select(Organization).where(Organization.id == organization_id).with_for_update())

    def get_active_conversation_routing_configuration(
        self, *, organization_id: uuid.UUID
    ) -> ConversationRoutingConfiguration | None:
        return self.session.scalar(
            select(ConversationRoutingConfiguration)
            .where(
                ConversationRoutingConfiguration.organization_id == organization_id,
                ConversationRoutingConfiguration.ownership_scope == "organization",
                ConversationRoutingConfiguration.configuration_status == "active",
            )
            .order_by(
                ConversationRoutingConfiguration.created_at.desc(),
                ConversationRoutingConfiguration.routing_configuration_id.asc(),
            )
            .limit(1)
        )

    def create_conversation_routing_configuration(
        self,
        *,
        organization_id: uuid.UUID,
        data_origin: str,
        configuration_version: str,
        intent_catalog: list[dict[str, Any]],
        provider_chain: list[dict[str, Any]],
        confidence_thresholds: dict[str, Any],
        fallback_behavior: dict[str, Any],
        context_window_policy: dict[str, Any],
        semantic_configuration: dict[str, Any],
        configuration_hash: str,
    ) -> ConversationRoutingConfiguration:
        record = ConversationRoutingConfiguration(
            organization_id=organization_id,
            ownership_scope="organization",
            data_origin=data_origin,
            configuration_version=configuration_version,
            configuration_status="active",
            intent_catalog=list(intent_catalog),
            provider_chain=list(provider_chain),
            confidence_thresholds=dict(confidence_thresholds),
            fallback_behavior=dict(fallback_behavior),
            context_window_policy=dict(context_window_policy),
            semantic_configuration=dict(semantic_configuration),
            configuration_hash=configuration_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_scoped_conversation_interaction_decision(
        self, *, conversation_turn_id: uuid.UUID, organization_id: uuid.UUID
    ) -> ConversationInteractionDecision | None:
        return self.session.scalar(
            select(ConversationInteractionDecision).where(
                ConversationInteractionDecision.conversation_turn_id == conversation_turn_id,
                ConversationInteractionDecision.organization_id == organization_id,
                ConversationInteractionDecision.ownership_scope == "organization",
            )
        )

    def create_conversation_interaction_decision(
        self,
        *,
        organization_id: uuid.UUID,
        data_origin: str,
        conversation_id: uuid.UUID,
        conversation_turn_id: uuid.UUID,
        conversation_context_package_id: uuid.UUID,
        routing_configuration_id: uuid.UUID,
        classification_evidence_id: uuid.UUID | None,
        intent: str,
        sub_intent: str | None,
        intent_parameters: dict[str, Any],
        confidence: float,
        resolution_method: str,
        resolution_provider: str,
        referenced_turn_ids: list[str],
        conversation_context_required: bool,
        retrieval_required: bool,
        generation_required: bool,
        target_runtime: str,
        embedding_used: bool,
        slm_used: bool,
        router_version: str,
        input_hash: str,
        decision_hash: str,
    ) -> ConversationInteractionDecision:
        record = ConversationInteractionDecision(
            organization_id=organization_id,
            ownership_scope="organization",
            data_origin=data_origin,
            conversation_id=conversation_id,
            conversation_turn_id=conversation_turn_id,
            conversation_context_package_id=conversation_context_package_id,
            routing_configuration_id=routing_configuration_id,
            classification_evidence_id=classification_evidence_id,
            intent=intent,
            sub_intent=sub_intent,
            intent_parameters=dict(intent_parameters),
            confidence=max(0.0, min(float(confidence), 1.0)),
            resolution_method=resolution_method,
            resolution_provider=resolution_provider,
            referenced_turn_ids=list(referenced_turn_ids),
            conversation_context_required=bool(conversation_context_required),
            retrieval_required=bool(retrieval_required),
            generation_required=bool(generation_required),
            target_runtime=target_runtime,
            embedding_used=bool(embedding_used),
            slm_used=bool(slm_used),
            router_version=router_version,
            input_hash=input_hash,
            decision_hash=decision_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_conversation(
        self,
        *,
        assistant_id: uuid.UUID | None = None,
        assistant_session_id: uuid.UUID | None = None,
        conversation_status: str = "active",
        conversation_title: str | None = None,
        conversation_reference: str | None = None,
        requested_by: str | None = None,
        runtime_context: dict[str, Any] | None = None,
        conversation_metadata: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None,
        data_origin: str,
    ) -> Conversation:
        if assistant_session_id is not None and organization_id is not None:
            self._require_conversation_session(
                assistant_session_id=assistant_session_id,
                organization_id=organization_id,
                assistant_id=assistant_id,
            )
        record = Conversation(
            organization_id=organization_id,
            ownership_scope="organization" if organization_id else "legacy_unscoped",
            data_origin=data_origin,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            conversation_status=conversation_status,
            conversation_title=conversation_title,
            conversation_reference=conversation_reference,
            requested_by=requested_by,
            runtime_context=dict(runtime_context or {}),
            conversation_metadata=dict(conversation_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self.session.get(Conversation, conversation_id)

    def get_scoped_conversation(self, conversation_id: uuid.UUID, *, organization_id: uuid.UUID) -> Conversation | None:
        return self.session.scalar(
            select(Conversation).where(
                Conversation.conversation_id == conversation_id,
                Conversation.organization_id == organization_id,
                Conversation.ownership_scope == "organization",
            )
        )

    def attach_conversation_session(
        self,
        *,
        conversation_id: uuid.UUID,
        assistant_session_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Conversation | None:
        record = self.get_scoped_conversation(conversation_id, organization_id=organization_id)
        if record is None:
            return None
        self._require_conversation_session(
            assistant_session_id=assistant_session_id,
            organization_id=organization_id,
            assistant_id=record.assistant_id,
        )
        record.assistant_session_id = assistant_session_id
        self.session.add(record)
        self.session.flush()
        return record

    def list_conversations(
        self,
        *,
        assistant_id: uuid.UUID | None = None,
        conversation_status: str | None = None,
        limit: int = 100,
    ) -> list[Conversation]:
        statement = select(Conversation)
        if assistant_id is not None:
            statement = statement.where(Conversation.assistant_id == assistant_id)
        if conversation_status:
            statement = statement.where(Conversation.conversation_status == conversation_status)
        statement = statement.order_by(Conversation.created_at.desc(), Conversation.conversation_id.asc()).limit(
            max(1, min(int(limit), 500))
        )
        return list(self.session.scalars(statement).all())

    def list_scoped_conversations(
        self,
        *,
        organization_id: uuid.UUID | None,
        assistant_id: uuid.UUID | None = None,
        conversation_status: str | None = None,
        limit: int = 100,
    ) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.organization_id == organization_id,
            Conversation.ownership_scope == "organization",
            Conversation.data_origin != "validation",
            func.coalesce(Conversation.conversation_metadata["scenario"].as_string(), "") != "local_product_acceptance",
            func.coalesce(Conversation.conversation_metadata["execution_key"].as_string(), "") == "",
        )
        if assistant_id is not None:
            statement = statement.where(Conversation.assistant_id == assistant_id)
        if conversation_status:
            statement = statement.where(Conversation.conversation_status == conversation_status)
        statement = statement.order_by(Conversation.created_at.desc()).limit(max(1, min(limit, 500)))
        return list(self.session.scalars(statement).all())

    def find_scoped_turn_by_idempotency_key(
        self,
        *,
        organization_id: uuid.UUID,
        assistant_id: uuid.UUID,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        statement = (
            select(ConversationTurn)
            .where(
                ConversationTurn.organization_id == organization_id,
                ConversationTurn.assistant_id == assistant_id,
                ConversationTurn.turn_role == "user",
                ConversationTurn.turn_metadata["idempotency_key"].as_string() == idempotency_key,
            )
            .order_by(ConversationTurn.created_at.asc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def set_conversation_title_if_empty(self, conversation_id: uuid.UUID, title: str) -> Conversation | None:
        record = self.get_conversation(conversation_id)
        if record is None:
            return None
        if not record.conversation_title:
            record.conversation_title = title
            self.session.add(record)
            self.session.flush()
        return record

    def create_conversation_turn(
        self,
        *,
        conversation_id: uuid.UUID,
        turn_index: int,
        turn_role: str,
        assistant_id: uuid.UUID | None = None,
        assistant_session_id: uuid.UUID | None = None,
        assistant_run_id: uuid.UUID | None = None,
        assistant_response_id: uuid.UUID | None = None,
        deterministic_interaction_plan_id: uuid.UUID | None = None,
        deterministic_input_fingerprint: str | None = None,
        turn_status: str = "recorded",
        input_text: str | None = None,
        output_text: str | None = None,
        response_format: str = "markdown",
        citation_summary: dict[str, Any] | None = None,
        ordered_citations: list[dict[str, Any]] | None = None,
        turn_metadata: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None,
        data_origin: str,
    ) -> ConversationTurn:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError("conversation lineage is unavailable")
        if organization_id != conversation.organization_id:
            raise ValueError("conversation turn organization is inconsistent with conversation")
        if assistant_id is not None and assistant_id != conversation.assistant_id:
            raise ValueError("conversation turn assistant is inconsistent with conversation")
        if assistant_session_id is not None and assistant_session_id != conversation.assistant_session_id:
            raise ValueError("conversation turn session is inconsistent with conversation")
        if assistant_response_id is not None:
            response = self.get_assistant_response(assistant_response_id)
            if response is None:
                raise ValueError("assistant response lineage is unavailable")
            if (
                response.organization_id != conversation.organization_id
                or response.assistant_id != conversation.assistant_id
                or response.assistant_session_id != conversation.assistant_session_id
            ):
                raise ValueError("assistant response lineage is inconsistent with conversation")
            assistant_id = response.assistant_id
            assistant_session_id = response.assistant_session_id
        else:
            assistant_id = conversation.assistant_id
            assistant_session_id = conversation.assistant_session_id
        record = ConversationTurn(
            organization_id=organization_id,
            ownership_scope="organization" if organization_id else "legacy_unscoped",
            data_origin=data_origin,
            conversation_id=conversation_id,
            assistant_id=assistant_id,
            assistant_session_id=assistant_session_id,
            assistant_run_id=assistant_run_id,
            assistant_response_id=assistant_response_id,
            deterministic_interaction_plan_id=deterministic_interaction_plan_id,
            deterministic_input_fingerprint=deterministic_input_fingerprint,
            turn_index=max(0, int(turn_index or 0)),
            turn_role=turn_role,
            turn_status=turn_status,
            input_text=input_text,
            output_text=output_text,
            response_format=response_format,
            citation_summary=dict(citation_summary or {}),
            ordered_citations=list(ordered_citations or []),
            turn_metadata=dict(turn_metadata or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_conversation_turn(self, conversation_turn_id: uuid.UUID) -> ConversationTurn | None:
        return self.session.get(ConversationTurn, conversation_turn_id)

    def list_conversation_turns(self, conversation_id: uuid.UUID, *, limit: int = 100) -> list[ConversationTurn]:
        statement = (
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.turn_index.asc(), ConversationTurn.created_at.asc())
            .limit(max(1, min(int(limit), 500)))
        )
        return list(self.session.scalars(statement).all())

    def get_next_conversation_turn_index(self, conversation_id: uuid.UUID) -> int:
        turns = self.list_conversation_turns(conversation_id, limit=500)
        if not turns:
            return 0
        return max(int(turn.turn_index or 0) for turn in turns) + 1

    def find_conversation_turn_by_assistant_response(
        self,
        *,
        conversation_id: uuid.UUID,
        assistant_response_id: uuid.UUID,
    ) -> ConversationTurn | None:
        statement = (
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .where(ConversationTurn.assistant_response_id == assistant_response_id)
            .order_by(ConversationTurn.turn_index.asc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def find_conversation_turn_for_assistant_response(
        self, assistant_response_id: uuid.UUID
    ) -> ConversationTurn | None:
        return self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.assistant_response_id == assistant_response_id)
            .order_by(ConversationTurn.created_at.asc(), ConversationTurn.conversation_turn_id.asc())
            .limit(1)
        )

    def _candidate_assistant_run_ids_from_value(self, value: Any) -> list[uuid.UUID]:
        candidates: list[uuid.UUID] = []
        if isinstance(value, dict):
            for key in ("assistant_run_id", "assistant_runtime_id"):
                raw_value = value.get(key)
                if raw_value is None:
                    continue
                try:
                    candidates.append(uuid.UUID(str(raw_value)))
                except (TypeError, ValueError):
                    continue
            for nested_value in value.values():
                candidates.extend(self._candidate_assistant_run_ids_from_value(nested_value))
        elif isinstance(value, list):
            for nested_value in value:
                candidates.extend(self._candidate_assistant_run_ids_from_value(nested_value))
        return candidates

    def _candidate_assistant_run_ids_from_metadata(self, *metadata_items: dict[str, Any] | None) -> list[uuid.UUID]:
        candidates: list[uuid.UUID] = []
        for metadata in metadata_items:
            candidates.extend(self._candidate_assistant_run_ids_from_value(metadata))
        return candidates

    def resolve_assistant_run_id_for_response(self, assistant_response_id: uuid.UUID) -> uuid.UUID | None:
        response = self.get_assistant_response(assistant_response_id)
        if response is None:
            return None
        citation_verification = (
            self.get_citation_verification(response.citation_verification_id)
            if response.citation_verification_id
            else None
        )
        if (
            citation_verification is not None
            and citation_verification.assistant_runtime_id is not None
            and self.get_assistant_runtime_run(citation_verification.assistant_runtime_id) is not None
        ):
            return citation_verification.assistant_runtime_id
        llm_execution = self.get_llm_execution(response.llm_execution_id) if response.llm_execution_id else None
        prompt = (
            self.get_prompt_package(llm_execution.prompt_package_id)
            if llm_execution is not None and llm_execution.prompt_package_id
            else None
        )
        context = (
            self.get_context_package(prompt.context_package_id)
            if prompt is not None and prompt.context_package_id
            else None
        )
        search = (
            self.get_assistant_search_execution(context.search_execution_id)
            if context is not None and context.search_execution_id
            else None
        )
        retrieval_plan = (
            self.get_assistant_retrieval_plan(search.retrieval_plan_id)
            if search is not None and search.retrieval_plan_id
            else None
        )
        execution_plan = (
            self.get_assistant_retrieval_execution_plan(search.execution_plan_id)
            if search is not None and search.execution_plan_id
            else None
        )
        candidates = self._candidate_assistant_run_ids_from_metadata(
            response.response_metadata,
            llm_execution.request_payload_metadata if llm_execution is not None else None,
            llm_execution.raw_output_metadata if llm_execution is not None else None,
            llm_execution.cost_metadata if llm_execution is not None else None,
            prompt.prompt_metadata if prompt is not None else None,
            context.package_metadata if context is not None else None,
            search.execution_metadata if search is not None else None,
            retrieval_plan.runtime_metadata if retrieval_plan is not None else None,
            execution_plan.readiness_metadata if execution_plan is not None else None,
        )
        for candidate in candidates:
            if self.get_assistant_runtime_run(candidate) is not None:
                return candidate
        return None

    def attach_assistant_response_turn(
        self,
        *,
        conversation_id: uuid.UUID,
        assistant_response_id: uuid.UUID,
        turn_metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn | None:
        conversation = self.get_conversation(conversation_id)
        response = self.get_assistant_response(assistant_response_id)
        if conversation is None or response is None:
            return None
        if (
            conversation.organization_id != response.organization_id
            or conversation.assistant_id != response.assistant_id
            or conversation.assistant_session_id != response.assistant_session_id
        ):
            raise ValueError("assistant response lineage is inconsistent with conversation")
        assistant_run_id = self.resolve_assistant_run_id_for_response(assistant_response_id)
        existing = self.find_conversation_turn_for_assistant_response(assistant_response_id)
        if existing is not None:
            if existing.conversation_id != conversation_id:
                raise ValueError("assistant response is already attached to another conversation")
            if (
                existing.organization_id != conversation.organization_id
                or existing.ownership_scope != conversation.ownership_scope
                or existing.assistant_id != conversation.assistant_id
                or existing.assistant_session_id != conversation.assistant_session_id
                or existing.assistant_response_id != response.assistant_response_id
            ):
                raise ValueError("existing conversation turn lineage is inconsistent")
            if existing.assistant_run_id is None and assistant_run_id is not None:
                existing.assistant_run_id = assistant_run_id
                self.session.add(existing)
                self.session.flush()
            return existing
        return self.create_conversation_turn(
            organization_id=conversation.organization_id,
            data_origin=conversation.data_origin,
            conversation_id=conversation.conversation_id,
            assistant_id=response.assistant_id,
            assistant_session_id=response.assistant_session_id,
            assistant_run_id=assistant_run_id,
            assistant_response_id=response.assistant_response_id,
            turn_index=self.get_next_conversation_turn_index(conversation.conversation_id),
            turn_role="assistant",
            turn_status="completed",
            output_text=response.response_text,
            response_format=response.response_format,
            citation_summary={
                "citation_verification_passed": bool(response.citation_verification_passed),
                "verified_citation_count": int(response.verified_citation_count or 0),
                "missing_citation_count": int(response.missing_citation_count or 0),
                "invalid_citation_count": int(response.invalid_citation_count or 0),
            },
            ordered_citations=list(response.ordered_citations or []),
            turn_metadata=dict(turn_metadata or {}),
        )

    def mark_assistant_run_completed(
        self,
        assistant_run_id: uuid.UUID,
        *,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> AssistantRuntimeRun | None:
        record = self.get_assistant_runtime_run(assistant_run_id)
        if record is None:
            return None
        record.run_status = "completed"
        record.execution_state = "completed"
        record.completed_at = datetime.now(UTC)
        if record.recovery_state is not None:
            record.recovery_state = "completed"
            record.recovery_owner = None
            record.recovery_lease_expires_at = None
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_assistant_run_failed(
        self,
        assistant_run_id: uuid.UUID,
        *,
        failure_reason: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> AssistantRuntimeRun | None:
        record = self.get_assistant_runtime_run(assistant_run_id)
        if record is None:
            return None
        record.run_status = "failed"
        record.execution_state = "failed"
        record.failed_at = datetime.now(UTC)
        record.failure_reason = failure_reason
        if record.recovery_state is not None:
            record.recovery_state = "failed"
            record.recovery_owner = None
            record.recovery_lease_expires_at = None
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record

    def mark_assistant_run_blocked(
        self,
        assistant_run_id: uuid.UUID,
        *,
        failure_reason: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> AssistantRuntimeRun | None:
        record = self.get_assistant_runtime_run(assistant_run_id)
        if record is None:
            return None
        record.run_status = "blocked"
        record.execution_state = "blocked"
        record.failure_reason = failure_reason
        if record.recovery_state is not None and record.recovery_state != "uncertain":
            record.recovery_state = "blocked"
            record.recovery_owner = None
            record.recovery_lease_expires_at = None
        record.runtime_metadata = {**(record.runtime_metadata or {}), **dict(runtime_metadata or {})}
        self.session.add(record)
        self.session.flush()
        return record
