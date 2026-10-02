from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]

KNOWLEDGE_INDEX_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class KnowledgeIndexEvidenceV1:
    """Canonical read contract for persisted PostgreSQL knowledge-index evidence.

    PostgreSQL remains authoritative. ``organization_id`` is required in the
    contract even though ``KnowledgeDocument`` does not carry tenant scope
    directly; readers resolve that scope through the persisted DocumentVersion
    lineage referenced by the indexed document.
    """

    knowledge_document_id: uuid.UUID
    organization_id: uuid.UUID
    artifact_id: str
    publication_id: str
    document_record_id: str | None
    document_version_id: str | None
    status: str
    index_version: int
    content_signature: str
    created_at: datetime
    updated_at: datetime
    metadata: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = KNOWLEDGE_INDEX_EVIDENCE_CONTRACT_VERSION
