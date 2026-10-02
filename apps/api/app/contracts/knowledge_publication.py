from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]

KNOWLEDGE_PUBLICATION_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class KnowledgePublicationEvidenceV1:
    """Canonical read contract for persisted Knowledge Publication evidence.

    Knowledge Publication runtime evidence is persisted in PostgreSQL as a
    ``RuntimePersistenceRecord`` with domain ``knowledge_publication`` and type
    ``publication_result``. The persisted record, not the in-memory runtime
    result, is authoritative for downstream Knowledge Index gates.
    """

    evidence_id: uuid.UUID
    organization_id: uuid.UUID
    execution_id: str
    artifact_id: str | None
    processing_session_id: str | None
    publication_id: str | None
    publication_status: str
    publication_completed: bool
    publication_succeeded: bool
    knowledge_published: bool
    published_chunk_count: int
    record_persistence_status: str
    occurred_at: datetime
    persisted_at: datetime | None
    payload: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = KNOWLEDGE_PUBLICATION_EVIDENCE_CONTRACT_VERSION
