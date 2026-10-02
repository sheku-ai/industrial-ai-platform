"""Platform Worker product contracts.

These contracts define the Sprint 9.2 worker boundary. They intentionally avoid
legacy worker names, customer-specific terminology, fixed document taxonomies,
fixed organizational hierarchies, and hardcoded vector collection names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class WorkerJobStatus(StrEnum):
    """Generic lifecycle states for platform worker jobs."""

    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class WorkerJobType(StrEnum):
    """Generic job categories owned by the platform runtime."""

    INGESTION = "ingestion"
    ARTIFACT_PUBLICATION = "artifact_publication"
    CHUNK_PERSISTENCE = "chunk_persistence"
    INDEXING_REQUEST = "indexing_request"


@dataclass(frozen=True)
class WorkerNodeRef:
    """Runtime identity of a worker node.

    The node name is an operational identifier only. It must not encode customer,
    country, plant, site, department, asset, or process assumptions.
    """

    node_id: str
    hostname: str | None = None
    capabilities: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JobLease:
    """A time-bounded claim over a persisted platform job."""

    job_id: UUID
    organization_id: UUID
    job_type: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    locked_by: str
    locked_at: datetime
    lease_expires_at: datetime
    pipeline_name: str | None = None
    pipeline_version: str | None = None
    adapter_profile: dict[str, Any] = field(default_factory=dict)
    chunking_profile: dict[str, Any] = field(default_factory=dict)
    quality_profile: dict[str, Any] = field(default_factory=dict)
    publication_profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Context provided to a worker execution attempt."""

    worker: WorkerNodeRef
    lease: JobLease
    correlation_id: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerExecutionResult:
    """Deterministic result returned by a worker execution attempt."""

    job_id: UUID
    status: WorkerJobStatus
    message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[dict[str, Any], ...] = ()
    chunks: tuple[dict[str, Any], ...] = ()
    indexing_requests: tuple[dict[str, Any], ...] = ()
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RetryDecision:
    """Retry decision produced after a failed worker execution attempt."""

    retryable: bool
    next_status: WorkerJobStatus
    next_attempt_count: int
    backoff_seconds: int
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class PipelineStateTransition:
    """Persistable state transition for a platform runtime job."""

    job_id: UUID
    from_status: str
    to_status: WorkerJobStatus
    reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ArtifactPublicationRequest:
    """Request to publish a worker artifact into object storage."""

    organization_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    artifact_type: str
    media_type: str | None
    content: bytes
    suggested_object_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactPublicationResult:
    """Descriptor returned after artifact publication.

    This descriptor is intended to be persisted as product state in
    `documents.artifacts`. The object store remains artifact storage only.
    """

    organization_id: UUID
    document_record_id: UUID
    document_version_id: UUID
    artifact_type: str
    media_type: str | None
    object_store_provider: str
    bucket: str
    object_key: str
    checksum_sha256: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
