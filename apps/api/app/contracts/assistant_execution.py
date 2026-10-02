from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]

ASSISTANT_EXECUTION_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class AssistantExecutionEvidenceV1:
    """Canonical read contract for persisted organization-scoped assistant execution evidence.

    PostgreSQL remains authoritative. This contract projects evidence persisted
    by ``AssistantRuntimeRun``. Only organization-owned runtime runs may cross
    this boundary; legacy or global scope must not be inferred into a tenant.
    """

    assistant_run_id: uuid.UUID
    organization_id: uuid.UUID
    assistant_id: uuid.UUID
    assistant_session_id: uuid.UUID
    ownership_scope: str
    data_origin: str
    run_status: str
    requested_query: str | None
    selected_search_mode: str
    selected_runtime_domain: str
    execution_state: str
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    runtime_metadata: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = ASSISTANT_EXECUTION_EVIDENCE_CONTRACT_VERSION
