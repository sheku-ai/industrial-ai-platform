from __future__ import annotations

import uuid

from app.contracts.conversation_event import ConversationEventEvidenceV1
from app.models.assistant_runtime import ConversationTurn


def project_conversation_event_evidence_v1(
    turn: ConversationTurn,
    *,
    organization_id: uuid.UUID,
) -> ConversationEventEvidenceV1:
    """Project persisted conversation-turn evidence into the canonical v1 contract.

    The projection accepts only organization-owned ``ConversationTurn`` rows
    and validates the requested tenant against persisted PostgreSQL scope.
    Legacy-unscoped turns must never be inferred into an organization.
    """

    if turn.ownership_scope != "organization":
        raise ValueError("conversation event evidence requires organization ownership scope")
    if turn.organization_id is None:
        raise ValueError("conversation event evidence requires persisted organization_id")
    if turn.organization_id != organization_id:
        raise ValueError("conversation event evidence does not match requested organization scope")

    return ConversationEventEvidenceV1(
        conversation_turn_id=turn.conversation_turn_id,
        organization_id=turn.organization_id,
        conversation_id=turn.conversation_id,
        ownership_scope=turn.ownership_scope,
        data_origin=turn.data_origin,
        assistant_id=turn.assistant_id,
        assistant_session_id=turn.assistant_session_id,
        assistant_run_id=turn.assistant_run_id,
        assistant_response_id=turn.assistant_response_id,
        request_id=turn.request_id,
        turn_index=turn.turn_index,
        turn_role=turn.turn_role,
        turn_status=turn.turn_status,
        input_text=turn.input_text,
        output_text=turn.output_text,
        response_format=turn.response_format,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
        citation_summary=dict(turn.citation_summary or {}),
        ordered_citations=tuple(dict(citation) for citation in (turn.ordered_citations or [])),
        turn_metadata=dict(turn.turn_metadata or {}),
    )
