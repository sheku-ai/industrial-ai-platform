from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import Conversation, ConversationTurn
from app.services.assistant_execution_conversation_gate import (
    evaluate_assistant_execution_conversation_gate_v1,
    serialize_assistant_execution_conversation_gate_v1,
)
from app.services.conversation_event_evidence_reader import read_conversation_event_evidence_v1

PRODUCT_ACCEPTANCE_CONVERSATION_EVIDENCE_SCHEMA_VERSION = "1"


def _issue(code: str, message: str, *, component: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "message": message,
    }


def _assistant_execution_payload(gate_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": "AssistantExecutionEvidenceV1",
        "assistant_run_id": gate_payload.get("assistant_run_id"),
        "organization_id": gate_payload.get("organization_id"),
        "assistant_id": gate_payload.get("assistant_id"),
        "assistant_session_id": gate_payload.get("assistant_session_id"),
        "run_status": gate_payload.get("run_status"),
        "execution_state": gate_payload.get("execution_state"),
        "authority": gate_payload.get("authority"),
    }


def _conversation_event_payload(evidence: Any) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "contract": "ConversationEventEvidenceV1",
        "contract_version": evidence.contract_version,
        "conversation_turn_id": str(evidence.conversation_turn_id),
        "organization_id": str(evidence.organization_id),
        "conversation_id": str(evidence.conversation_id),
        "ownership_scope": evidence.ownership_scope,
        "data_origin": evidence.data_origin,
        "assistant_id": str(evidence.assistant_id) if evidence.assistant_id else None,
        "assistant_session_id": str(evidence.assistant_session_id) if evidence.assistant_session_id else None,
        "assistant_run_id": str(evidence.assistant_run_id) if evidence.assistant_run_id else None,
        "assistant_response_id": str(evidence.assistant_response_id) if evidence.assistant_response_id else None,
        "request_id": evidence.request_id,
        "turn_index": evidence.turn_index,
        "turn_role": evidence.turn_role,
        "turn_status": evidence.turn_status,
        "response_format": evidence.response_format,
        "output_present": bool(evidence.output_text),
        "created_at": evidence.created_at.isoformat(),
        "updated_at": evidence.updated_at.isoformat(),
    }


def build_assistant_conversation_runtime_evidence(
    session: Session,
    *,
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID,
    assistant_run_id: uuid.UUID,
    expected_assistant_id: uuid.UUID,
    expected_assistant_response_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Verify Assistant Execution -> Conversation Event from PostgreSQL evidence."""

    conversation = session.scalar(
        select(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.organization_id == organization_id,
            Conversation.ownership_scope == "organization",
        )
    )
    issues: list[dict[str, Any]] = []
    if conversation is None:
        issues.append(
            _issue(
                "conversation_evidence_missing",
                "Product Acceptance requires a persisted organization-scoped conversation.",
                component="conversation_evidence",
            )
        )
        return {
            "runtime_evidence_schema_version": PRODUCT_ACCEPTANCE_CONVERSATION_EVIDENCE_SCHEMA_VERSION,
            "authority": "postgresql",
            "organization_id": str(organization_id),
            "conversation_id": str(conversation_id),
            "assistant_run_id": str(assistant_run_id),
            "assistant_execution": None,
            "conversation_event": None,
            "ready": False,
            "blocking_issues": issues,
        }

    assistant_gate = evaluate_assistant_execution_conversation_gate_v1(
        session,
        organization_id=organization_id,
        conversation=conversation,
        assistant_run_id=assistant_run_id,
    )
    assistant_gate_payload = serialize_assistant_execution_conversation_gate_v1(assistant_gate)
    issues.extend(dict(item) for item in assistant_gate.blocking_issues)

    if conversation.assistant_id != expected_assistant_id:
        issues.append(
            _issue(
                "conversation_assistant_mismatch",
                "Conversation does not belong to the Product Acceptance assistant.",
                component="conversation_evidence",
            )
        )

    turn = session.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.organization_id == organization_id,
            ConversationTurn.ownership_scope == "organization",
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.assistant_run_id == assistant_run_id,
            ConversationTurn.assistant_id == expected_assistant_id,
            ConversationTurn.turn_role == "assistant",
        )
        .order_by(ConversationTurn.turn_index.desc(), ConversationTurn.created_at.desc())
        .limit(1)
    )
    if turn is None:
        issues.append(
            _issue(
                "conversation_turn_evidence_missing",
                "Product Acceptance requires a persisted assistant ConversationTurn for the assistant run.",
                component="conversation_event_evidence",
            )
        )
        conversation_event = None
    else:
        conversation_event = read_conversation_event_evidence_v1(
            session,
            organization_id=organization_id,
            conversation_turn_id=turn.conversation_turn_id,
        )
        if conversation_event is None:
            issues.append(
                _issue(
                    "conversation_event_evidence_missing",
                    "ConversationTurn could not be projected to ConversationEventEvidenceV1.",
                    component="conversation_event_evidence",
                )
            )
        else:
            if conversation_event.conversation_id != conversation_id:
                issues.append(
                    _issue(
                        "conversation_event_conversation_mismatch",
                        "Conversation event does not match the Product Acceptance conversation.",
                        component="conversation_event_evidence",
                    )
                )
            if conversation_event.assistant_run_id != assistant_run_id:
                issues.append(
                    _issue(
                        "conversation_event_run_mismatch",
                        "Conversation event does not match the persisted assistant execution.",
                        component="conversation_event_evidence",
                    )
                )
            if conversation_event.assistant_id != expected_assistant_id:
                issues.append(
                    _issue(
                        "conversation_event_assistant_mismatch",
                        "Conversation event does not match the Product Acceptance assistant.",
                        component="conversation_event_evidence",
                    )
                )
            if conversation_event.assistant_session_id != conversation.assistant_session_id:
                issues.append(
                    _issue(
                        "conversation_event_session_mismatch",
                        "Conversation event and conversation do not share the same assistant session.",
                        component="conversation_event_evidence",
                    )
                )
            if conversation_event.turn_role != "assistant" or conversation_event.turn_status != "completed":
                issues.append(
                    _issue(
                        "conversation_event_not_completed",
                        "Product Acceptance requires a completed persisted assistant conversation event.",
                        component="conversation_event_evidence",
                    )
                )
            if not conversation_event.output_text:
                issues.append(
                    _issue(
                        "conversation_event_output_missing",
                        "Completed assistant conversation evidence requires persisted output_text.",
                        component="conversation_event_evidence",
                    )
                )
            if (
                expected_assistant_response_id is not None
                and conversation_event.assistant_response_id != expected_assistant_response_id
            ):
                issues.append(
                    _issue(
                        "conversation_event_response_mismatch",
                        "Conversation event does not reference the Product Acceptance assistant response.",
                        component="conversation_event_evidence",
                    )
                )

    assistant_execution = assistant_gate.assistant_execution_evidence
    if assistant_execution is not None:
        if assistant_execution.assistant_id != expected_assistant_id:
            issues.append(
                _issue(
                    "assistant_execution_assistant_mismatch",
                    "Assistant execution does not belong to the Product Acceptance assistant.",
                    component="assistant_execution_evidence",
                )
            )
        if assistant_execution.assistant_run_id != assistant_run_id:
            issues.append(
                _issue(
                    "assistant_execution_run_mismatch",
                    "AssistantExecutionEvidenceV1 does not match the requested assistant run.",
                    component="assistant_execution_evidence",
                )
            )

    return {
        "runtime_evidence_schema_version": PRODUCT_ACCEPTANCE_CONVERSATION_EVIDENCE_SCHEMA_VERSION,
        "authority": "postgresql",
        "organization_id": str(organization_id),
        "conversation_id": str(conversation_id),
        "assistant_id": str(expected_assistant_id),
        "assistant_run_id": str(assistant_run_id),
        "assistant_response_id": str(expected_assistant_response_id) if expected_assistant_response_id else None,
        "assistant_execution_gate": assistant_gate_payload,
        "assistant_execution": _assistant_execution_payload(assistant_gate_payload)
        if assistant_execution is not None
        else None,
        "conversation_event": _conversation_event_payload(conversation_event),
        "ready": assistant_execution is not None and conversation_event is not None and not issues,
        "blocking_issues": issues,
    }
