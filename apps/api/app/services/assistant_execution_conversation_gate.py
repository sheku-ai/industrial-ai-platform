from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.assistant_execution import AssistantExecutionEvidenceV1
from app.models.assistant_runtime import Conversation
from app.services.assistant_execution_evidence_reader import read_assistant_execution_evidence_v1

ASSISTANT_EXECUTION_CONVERSATION_GATE_VERSION = "v1"


@dataclass(frozen=True)
class AssistantExecutionConversationGateV1:
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_run_id: uuid.UUID
    assistant_execution_evidence: AssistantExecutionEvidenceV1 | None
    ready: bool
    blocking_issues: tuple[dict[str, Any], ...]
    gate_version: str = ASSISTANT_EXECUTION_CONVERSATION_GATE_VERSION


def _issue(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": "assistant_execution_evidence",
        "message": message,
    }


def evaluate_assistant_execution_conversation_gate_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    conversation: Conversation,
    assistant_run_id: uuid.UUID,
) -> AssistantExecutionConversationGateV1:
    """Authorize an assistant conversation event from persisted run evidence.

    The assistant run is read through the canonical organization-scoped contract.
    Conversation lineage must match the persisted assistant and session. Transient
    runtime metadata is never accepted as authority for the boundary.
    """

    evidence = read_assistant_execution_evidence_v1(
        session,
        organization_id=organization_id,
        assistant_run_id=assistant_run_id,
    )
    blocking_issues: list[dict[str, Any]] = []
    if evidence is None:
        blocking_issues.append(
            _issue(
                "assistant_execution_evidence_missing",
                "Conversation event requires persisted organization-scoped assistant execution evidence.",
            )
        )
    else:
        if conversation.organization_id != evidence.organization_id:
            blocking_issues.append(
                _issue(
                    "assistant_execution_organization_mismatch",
                    "Assistant execution and conversation must belong to the same organization.",
                )
            )
        if conversation.assistant_id is not None and conversation.assistant_id != evidence.assistant_id:
            blocking_issues.append(
                _issue(
                    "assistant_execution_assistant_mismatch",
                    "Assistant execution does not belong to the conversation assistant.",
                )
            )
        if (
            conversation.assistant_session_id is not None
            and conversation.assistant_session_id != evidence.assistant_session_id
        ):
            blocking_issues.append(
                _issue(
                    "assistant_execution_session_mismatch",
                    "Assistant execution does not belong to the conversation session.",
                )
            )
        if evidence.run_status in {"blocked", "failed", "disabled"}:
            blocking_issues.append(
                _issue(
                    "assistant_execution_terminal_failure",
                    "Conversation event cannot consume blocked, failed, or disabled assistant execution evidence.",
                )
            )
        if evidence.execution_state in {"blocked", "failed", "disabled"}:
            blocking_issues.append(
                _issue(
                    "assistant_execution_state_invalid",
                    "Conversation event cannot consume assistant execution in a terminal failure state.",
                )
            )

    return AssistantExecutionConversationGateV1(
        organization_id=organization_id,
        conversation_id=conversation.conversation_id,
        assistant_run_id=assistant_run_id,
        assistant_execution_evidence=evidence,
        ready=not blocking_issues,
        blocking_issues=tuple(blocking_issues),
    )


def serialize_assistant_execution_conversation_gate_v1(
    gate: AssistantExecutionConversationGateV1,
) -> dict[str, Any]:
    evidence = gate.assistant_execution_evidence
    return {
        "gate_version": gate.gate_version,
        "organization_id": str(gate.organization_id),
        "conversation_id": str(gate.conversation_id),
        "assistant_run_id": str(gate.assistant_run_id),
        "assistant_id": str(evidence.assistant_id) if evidence is not None else None,
        "assistant_session_id": str(evidence.assistant_session_id) if evidence is not None else None,
        "run_status": evidence.run_status if evidence is not None else None,
        "execution_state": evidence.execution_state if evidence is not None else None,
        "ready": gate.ready,
        "blocking_issues": [dict(item) for item in gate.blocking_issues],
        "authority": "postgresql",
        "contract": "AssistantExecutionEvidenceV1",
    }
