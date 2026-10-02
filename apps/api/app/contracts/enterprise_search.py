from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]

ENTERPRISE_SEARCH_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class EnterpriseSearchEvidenceV1:
    """Canonical read contract for persisted Enterprise Search evidence.

    PostgreSQL remains authoritative. The current Enterprise Search runtime is
    materialized into ``RuntimePersistenceRecord`` rows. Organization scope is
    carried by the persisted search result payload and must be validated by
    projections/readers before evidence crosses a runtime boundary.
    """

    evidence_id: uuid.UUID
    organization_id: uuid.UUID
    execution_id: str
    search_session_id: str | None
    query: str
    normalized_query: str
    search_status: str
    ranking_model: str | None
    total_count: int
    result_count: int
    offset: int
    limit: int
    has_more: bool
    search_uses_postgresql: bool
    search_uses_postgresql_fts: bool
    semantic_search_used: bool
    embeddings_required: bool
    ai_required: bool
    persistence_status: str
    occurred_at: datetime
    persisted_at: datetime
    payload: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = ENTERPRISE_SEARCH_EVIDENCE_CONTRACT_VERSION
