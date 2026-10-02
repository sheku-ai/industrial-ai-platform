from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

JsonMapping = Mapping[str, Any]

PROCESSING_EVIDENCE_CONTRACT_VERSION = "v1"


@dataclass(frozen=True)
class ProcessingEvidenceV1:
    """Canonical read contract for persisted document processing evidence.

    PostgreSQL remains authoritative. This contract only projects the evidence
    already persisted by ``ProcessingRevision`` across runtime boundaries.
    """

    evidence_id: uuid.UUID
    organization_id: uuid.UUID
    document_record_id: uuid.UUID
    document_version_id: uuid.UUID
    runtime_execution_id: uuid.UUID
    runtime_attempt_id: uuid.UUID
    pipeline_profile_id: uuid.UUID | None
    pipeline_profile_revision: str
    adapter_key: str
    adapter_version: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    source_checksum_sha256: str | None
    content_unit_count: int
    chunk_count: int
    manifest_artifact_id: uuid.UUID | None
    configuration_snapshot: JsonMapping = field(default_factory=dict)
    contract_version: Literal["v1"] = PROCESSING_EVIDENCE_CONTRACT_VERSION
