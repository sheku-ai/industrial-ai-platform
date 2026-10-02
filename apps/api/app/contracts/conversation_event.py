from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]
JsonSequence = Sequence[Mapping[str, Any]]

CONVERSATION_EVENT_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class ConversationEventEvidenceV1:
    """Canonical read contract for persisted organization-scoped conversation events.

    PostgreSQL remains authoritative. ``ConversationTurn`` is the persisted
    event boundary for conversation activity. Only organization-owned turns may
    cross this contract; legacy-unscoped rows must never be inferred into a
    tenant.
    """

    conversation_turn_id: uuid.UUID
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    ownership_scope: str
    data_origin: str
    assistant_id: uuid.UUID | None
    assistant_session_id: uuid.UUID | None
    assistant_run_id: uuid.UUID | None
    assistant_response_id: uuid.UUID | None
    request_id: str | None
    turn_index: int
    turn_role: str
    turn_status: str
    input_text: str | None
    output_text: str | None
    response_format: str
    created_at: datetime
    updated_at: datetime
    citation_summary: JsonMapping = field(default_factory=dict)
    ordered_citations: JsonSequence = field(default_factory=tuple)
    turn_metadata: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = CONVERSATION_EVENT_EVIDENCE_CONTRACT_VERSION
