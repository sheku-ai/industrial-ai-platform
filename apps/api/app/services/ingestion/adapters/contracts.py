from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AdapterCapability(StrEnum):
    """Product-level extraction capabilities.

    Capabilities are generic by design. They describe processing behavior, not
    customer-specific document types, departments, assets, countries, or business
    processes.
    """

    RICH_DOCUMENT_EXTRACTION = "rich_document_extraction"
    TEXT_EXTRACTION = "text_extraction"
    STRUCTURED_FILE_EXTRACTION = "structured_file_extraction"
    OCR_ENRICHMENT = "ocr_enrichment"
    TABLE_PRESERVATION = "table_preservation"
    SECTION_DETECTION = "section_detection"
    QUALITY_FILTERING = "quality_filtering"
    CHUNK_GENERATION = "chunk_generation"
    ARTIFACT_SERIALIZATION = "artifact_serialization"


@dataclass(frozen=True)
class IngestionSourceRef:
    """Generic source reference for an ingestion execution.

    The source can be an uploaded object, a connector object, an API payload, or a
    future provider. The contract intentionally avoids hardcoded document families
    or fixed metadata assumptions.
    """

    organization_id: uuid.UUID
    document_record_id: uuid.UUID | None
    document_version_id: uuid.UUID | None
    source_type: str
    uri: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    source_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionProfile:
    """Configurable extraction behavior loaded from PostgreSQL-backed state."""

    adapter_name: str
    adapter_version: str | None = None
    preferred_methods: tuple[str, ...] = ()
    allow_ocr: bool = False
    preserve_layout: bool = False
    preserve_tables: bool = True
    max_pages: int | None = None
    max_rows: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityProfile:
    """Configurable content quality profile."""

    min_chars: int = 80
    exclude_noise: bool = True
    exclude_low_value: bool = True
    accepted_content_types: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkingProfile:
    """Configurable chunking profile."""

    max_chars: int = 1200
    overlap_chars: int = 200
    min_chunk_chars: int = 120
    strategy: str = "section_aware"
    preserve_structure: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterExecutionContext:
    """Execution context passed into adapters and services."""

    ingestion_job_id: uuid.UUID
    organization_id: uuid.UUID
    requested_by: str | None = None
    correlation_id: str | None = None
    pipeline_name: str | None = None
    pipeline_version: str | None = None
    started_at: datetime | None = None
    runtime_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedContentBlock:
    """Adapter-neutral normalized content block."""

    block_key: str
    text: str
    content_type: str = "content"
    structure_ref: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionAdapterResult:
    """Output from an extraction adapter before chunking and artifact publishing."""

    source: IngestionSourceRef
    adapter_name: str
    adapter_version: str
    extraction_method: str
    blocks: tuple[NormalizedContentBlock, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentQualityDecision:
    """Quality decision for a normalized block or chunk candidate."""

    accepted: bool
    content_type: str
    reason: str | None = None
    score: float | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkCandidate:
    """Chunk candidate before database persistence and indexing."""

    chunk_key: str
    chunk_index: int
    text: str
    content_hash: str
    semantic_hash: str | None = None
    content_type: str | None = None
    section_ref: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactDescriptor:
    """Serialized artifact reference after publication or local preparation."""

    artifact_type: str
    media_type: str | None
    object_store_provider: str | None
    bucket: str | None
    object_key: str | None
    checksum_sha256: str | None
    size_bytes: int | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
