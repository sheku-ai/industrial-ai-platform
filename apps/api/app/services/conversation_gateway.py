"""Conversation Runtime validation gateway."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.assistant import AssistantRepository
from app.services.assistant_execution_conversation_gate import (
    evaluate_assistant_execution_conversation_gate_v1,
    serialize_assistant_execution_conversation_gate_v1,
)
from app.services.enterprise_search_session import issue, sort_issues

SUPPORTED_TURN_ROLES = {"user", "assistant", "system", "tool"}
SUPPORTED_CONVERSATION_STATUSES = {"active", "completed", "archived", "blocked", "failed", "disabled"}


def _uuid_or_issue(value: str | None, *, code: str, component: str, issues: list[dict[str, Any]]) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        issues.append(
            issue(code, "Conversation runtime requires a valid UUID.", component=component, item_id=str(value))
        )
        return None


def build_conversation_health(db: Session) -> dict[str, Any]:
    return {
        "conversation_health_schema_version": "1",
        "conversation_runtime_available": True,
        "conversation_runtime_status": "deterministic_conversation_runtime",
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }


def validate_conversation_creation(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assistant_id: str | None = None,
    assistant_session_id: str | None = None,
    conversation_status: str = "active",
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    assistant_uuid = _uuid_or_issue(
        assistant_id, code="assistant_id_invalid", component="conversation_gateway", issues=blocking_issues
    )
    session_uuid = _uuid_or_issue(
        assistant_session_id,
        code="assistant_session_id_invalid",
        component="conversation_gateway",
        issues=blocking_issues,
    )
    if conversation_status not in SUPPORTED_CONVERSATION_STATUSES:
        blocking_issues.append(
            issue(
                "conversation_status_invalid",
                "Conversation status is not supported.",
                component="conversation_gateway",
                item_id=conversation_status,
            )
        )
    if assistant_uuid is not None and repository.get_assistant_definition(assistant_uuid) is None:
        blocking_issues.append(
            issue(
                "assistant_not_found",
                "Conversation requires an existing assistant when assistant_id is provided.",
                component="conversation_gateway",
                item_id=str(assistant_uuid),
            )
        )
    if session_uuid is not None:
        assistant_session = repository.get_scoped_assistant_session(
            session_uuid,
            organization_id=organization_id,
        )
        if assistant_session is None:
            if repository.assistant_session_exists(session_uuid):
                blocking_issues.append(
                    issue(
                        "assistant_session_not_authorized_for_organization",
                        "Assistant session is not available in the authorized organization scope.",
                        component="conversation_gateway",
                        item_id=str(session_uuid),
                    )
                )
            else:
                blocking_issues.append(
                    issue(
                        "assistant_session_not_found",
                        "Conversation requires an existing assistant session when assistant_session_id is provided.",
                        component="conversation_gateway",
                        item_id=str(session_uuid),
                    )
                )
        elif assistant_uuid is not None and assistant_session.assistant_id != assistant_uuid:
            blocking_issues.append(
                issue(
                    "assistant_session_assistant_mismatch",
                    "Assistant session lineage does not match the conversation assistant.",
                    component="conversation_gateway",
                    item_id=str(session_uuid),
                )
            )
    ready = not blocking_issues
    return {
        "conversation_gateway_schema_version": "1",
        "conversation_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "assistant_id": str(assistant_uuid) if assistant_uuid else None,
        "assistant_session_id": str(session_uuid) if session_uuid else None,
        "conversation_status": conversation_status,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "blocking_issues": sort_issues(blocking_issues),
        "warnings": [],
    }


def validate_conversation_turn_creation(
    db: Session,
    *,
    conversation_id: str,
    turn_role: str,
    assistant_run_id: str | None = None,
    deterministic_interaction_plan_id: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    conversation_uuid = _uuid_or_issue(
        conversation_id, code="conversation_id_invalid", component="conversation_turn_gateway", issues=blocking_issues
    )
    conversation = repository.get_conversation(conversation_uuid) if conversation_uuid is not None else None
    if conversation_uuid is not None and conversation is None:
        blocking_issues.append(
            issue(
                "conversation_not_found",
                "Conversation turn requires an existing conversation.",
                component="conversation_turn_gateway",
                item_id=str(conversation_uuid),
            )
        )
    if turn_role not in SUPPORTED_TURN_ROLES:
        blocking_issues.append(
            issue(
                "turn_role_invalid",
                "Conversation turn role is not supported.",
                component="conversation_turn_gateway",
                item_id=turn_role,
            )
        )
    assistant_gate_payload: dict[str, Any] | None = None
    if turn_role == "assistant" and conversation is not None:
        run_uuid = _uuid_or_issue(
            assistant_run_id,
            code="assistant_run_id_invalid",
            component="conversation_turn_gateway",
            issues=blocking_issues,
        )
        if run_uuid is None and not assistant_run_id and not deterministic_interaction_plan_id:
            blocking_issues.append(
                issue(
                    "assistant_execution_evidence_required",
                    "Assistant conversation turns require persisted assistant execution evidence.",
                    component="conversation_turn_gateway",
                )
            )
        if run_uuid is not None:
            if organization_id is None:
                blocking_issues.append(
                    issue(
                        "organization_scope_required",
                        "Assistant conversation turns require an organization scope.",
                        component="conversation_turn_gateway",
                    )
                )
            else:
                assistant_gate = evaluate_assistant_execution_conversation_gate_v1(
                    db,
                    organization_id=organization_id,
                    conversation=conversation,
                    assistant_run_id=run_uuid,
                )
                assistant_gate_payload = serialize_assistant_execution_conversation_gate_v1(assistant_gate)
                blocking_issues.extend(assistant_gate.blocking_issues)
    ready = not blocking_issues
    return {
        "conversation_turn_gateway_schema_version": "1",
        "conversation_turn_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "conversation_id": str(conversation_uuid) if conversation_uuid else str(conversation_id),
        "turn_role": turn_role,
        "assistant_execution_evidence_gate": assistant_gate_payload,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "blocking_issues": sort_issues(list(blocking_issues)),
        "warnings": [],
    }


def validate_assistant_response_attachment(
    db: Session,
    *,
    conversation_id: str,
    assistant_response_id: str,
) -> dict[str, Any]:
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repository = AssistantRepository(db)
    conversation_uuid = _uuid_or_issue(
        conversation_id,
        code="conversation_id_invalid",
        component="conversation_response_gateway",
        issues=blocking_issues,
    )
    response_uuid = _uuid_or_issue(
        assistant_response_id,
        code="assistant_response_id_invalid",
        component="conversation_response_gateway",
        issues=blocking_issues,
    )
    conversation = repository.get_conversation(conversation_uuid) if conversation_uuid is not None else None
    response = repository.get_assistant_response(response_uuid) if response_uuid is not None else None
    if conversation_uuid is not None and conversation is None:
        blocking_issues.append(
            issue(
                "conversation_not_found",
                "Assistant response attachment requires an existing conversation.",
                component="conversation_response_gateway",
                item_id=str(conversation_uuid),
            )
        )
    if response_uuid is not None and response is None:
        blocking_issues.append(
            issue(
                "assistant_response_not_found",
                "Assistant response attachment requires an existing assistant response.",
                component="conversation_response_gateway",
                item_id=str(response_uuid),
            )
        )
    if conversation is not None and conversation.ownership_scope != "organization":
        blocking_issues.append(
            issue(
                "conversation_not_organization_scoped",
                "Assistant response attachment requires an organization-scoped conversation.",
                component="conversation_response_gateway",
                item_id=str(conversation.conversation_id),
            )
        )
    if response is not None and response.ownership_scope != "organization":
        blocking_issues.append(
            issue(
                "assistant_response_not_organization_scoped",
                "Assistant response attachment requires organization-scoped runtime evidence.",
                component="conversation_response_gateway",
                item_id=str(response.assistant_response_id),
            )
        )
    if (
        conversation is not None
        and response is not None
        and conversation.ownership_scope == "organization"
        and response.ownership_scope == "organization"
        and conversation.organization_id != response.organization_id
    ):
        blocking_issues.append(
            issue(
                "assistant_response_organization_mismatch",
                "Assistant response and conversation must belong to the same organization.",
                component="conversation_response_gateway",
                item_id=str(response.assistant_response_id),
            )
        )
    assistant_gate_payload: dict[str, Any] | None = None
    if conversation is not None and response is not None and conversation.organization_id is not None:
        verification = repository.get_citation_verification(response.citation_verification_id)
        assistant_run_id = verification.assistant_runtime_id if verification is not None else None
        if assistant_run_id is None:
            blocking_issues.append(
                issue(
                    "assistant_execution_lineage_missing",
                    "Assistant response requires persisted assistant execution lineage before conversation attachment.",
                    component="conversation_response_gateway",
                    item_id=str(response.assistant_response_id),
                )
            )
        else:
            assistant_gate = evaluate_assistant_execution_conversation_gate_v1(
                db,
                organization_id=conversation.organization_id,
                conversation=conversation,
                assistant_run_id=assistant_run_id,
            )
            assistant_gate_payload = serialize_assistant_execution_conversation_gate_v1(assistant_gate)
            blocking_issues.extend(assistant_gate.blocking_issues)
    existing = (
        repository.find_conversation_turn_by_assistant_response(
            conversation_id=conversation_uuid, assistant_response_id=response_uuid
        )
        if conversation_uuid and response_uuid
        else None
    )
    if existing is not None:
        warnings.append(
            issue(
                "conversation_turn_already_exists",
                "Conversation already has a turn for this assistant response.",
                component="conversation_response_gateway",
                severity="warning",
                item_id=str(existing.conversation_turn_id),
            )
        )
    ready = not blocking_issues
    return {
        "conversation_response_gateway_schema_version": "1",
        "conversation_response_gateway_ready": ready,
        "gateway_status": "ready" if ready else "blocked",
        "conversation_id": str(conversation_uuid) if conversation_uuid else str(conversation_id),
        "assistant_response_id": str(response_uuid) if response_uuid else str(assistant_response_id),
        "existing_conversation_turn_id": str(existing.conversation_turn_id) if existing is not None else None,
        "assistant_execution_evidence_gate": assistant_gate_payload,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "blocking_issues": sort_issues(list(blocking_issues)),
        "warnings": sort_issues(warnings),
    }
