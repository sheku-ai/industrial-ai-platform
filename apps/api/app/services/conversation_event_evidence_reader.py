from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.conversation_event import ConversationEventEvidenceV1
from app.models.assistant_runtime import ConversationTurn
from app.services.conversation_event_contract_projection import project_conversation_event_evidence_v1


def read_conversation_event_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> ConversationEventEvidenceV1 | None:
    """Read organization-scoped conversation event evidence from PostgreSQL."""

    turn = session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.conversation_turn_id == conversation_turn_id,
            ConversationTurn.organization_id == organization_id,
            ConversationTurn.ownership_scope == "organization",
        )
    )
    if turn is None:
        return None
    return project_conversation_event_evidence_v1(turn, organization_id=organization_id)
