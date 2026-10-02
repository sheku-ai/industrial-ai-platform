from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class IngestionContractError(ValueError):
    """Raised when an ingestion contract is internally inconsistent."""


class IngestionUnitType(StrEnum):
    TEXT_SECTION = "text_section"
    PAGE = "page"
    TABLE = "table"
    ROW = "row"
    CELL_GROUP = "cell_group"
    LIST = "list"
    STRUCTURED_OBJECT = "structured_object"
    ATTACHMENT_REFERENCE = "attachment_reference"


class IngestionStage(StrEnum):
    SOURCE_ACQUIRE = "source.acquire"
    SOURCE_VALIDATE = "source.validate"
    ADAPTER_RESOLVE = "adapter.resolve"
    CONTENT_EXTRACT = "content.extract"
    CONTENT_NORMALIZE = "content.normalize"
    CONTENT_CHUNK = "content.chunk"
    CONTENT_QUALITY_FILTER = "content.quality_filter"
    CONTENT_PERSIST = "content.persist"
    ARTIFACT_PUBLISH = "artifact.publish"
    LEXICAL_INDEX = "lexical.index"
    EMBEDDING_GENERATE = "embedding.generate"
    VECTOR_PUBLISH = "vector.publish"
    EXECUTION_FINALIZE = "execution.finalize"


class IngestionStageOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    FAILED_NON_BLOCKING = "failed_non_blocking"


class IngestionErrorCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CONTENT = "unsupported_content"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_INTEGRITY_FAILED = "source_integrity_failed"
    ADAPTER_NOT_CONFIGURED = "adapter_not_configured"
    ADAPTER_VALIDATION_FAILED = "adapter_validation_failed"
    EXTRACTION_FAILED = "extraction_failed"
    NORMALIZATION_FAILED = "normalization_failed"
    CHUNKING_FAILED = "chunking_failed"
    QUALITY_REJECTED = "quality_rejected"
    PERSISTENCE_FAILED = "persistence_failed"
    ARTIFACT_PUBLICATION_FAILED = "artifact_publication_failed"
    LEXICAL_INDEX_FAILED = "lexical_index_failed"
    OPTIONAL_ENRICHMENT_FAILED = "optional_enrichment_failed"
    CANCELLED = "cancelled"
    LEASE_LOST = "lease_lost"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class AdapterCapabilities:
    supported_media_types: frozenset[str]
    supported_signatures: frozenset[str] = frozenset()
    supported_container_types: frozenset[str] = frozenset()
    priority: int = 100
    requires_external_binary: bool = False
    supports_ocr: bool = False
    supports_structured_output: bool = False
    supports_cancellation: bool = True
    community_available: bool = True
    enterprise_available: bool = True

    def __post_init__(self) -> None:
        normalized_media_types = frozenset(_normalize_media_type(value) for value in self.supported_media_types)
        if not normalized_media_types:
            raise IngestionContractError("at least one supported media type is required")
        if self.priority < 0:
            raise IngestionContractError("adapter priority must be non-negative")
        object.__setattr__(self, "supported_media_types", normalized_media_types)


@dataclass(frozen=True)
class IngestionRequest:
    organization_id: UUID
    execution_id: UUID
    subject_type: str
    subject_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_reference: str
    declared_media_type: str
    original_file_name: str
    content_length: int | None = None
    checksum_sha256: str | None = None
    pipeline_profile_id: UUID | None = None
    adapter_hint: str | None = None
    metadata_template_id: UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.subject_type != "document_version":
            raise IngestionContractError("ingestion subject_type must be document_version")
        if self.subject_id != self.document_version_id:
            raise IngestionContractError("subject_id must equal document_version_id")
        if not self.source_reference.strip():
            raise IngestionContractError("source_reference is required")
        if not self.original_file_name.strip():
            raise IngestionContractError("original_file_name is required")
        if self.content_length is not None and self.content_length < 0:
            raise IngestionContractError("content_length must be non-negative")
        if self.checksum_sha256 is not None and not _is_sha256(self.checksum_sha256):
            raise IngestionContractError("checksum_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "declared_media_type", _normalize_media_type(self.declared_media_type))
        object.__setattr__(self, "source_reference", self.source_reference.strip())
        object.__setattr__(self, "original_file_name", self.original_file_name.strip())
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "options", dict(self.options))


@dataclass(frozen=True)
class AcquiredSource:
    source_reference: str
    local_path: str
    detected_media_type: str
    content_length: int
    checksum_sha256: str

    def __post_init__(self) -> None:
        if not self.source_reference.strip():
            raise IngestionContractError("source_reference is required")
        if not self.local_path.strip():
            raise IngestionContractError("local_path is required")
        if self.content_length < 0:
            raise IngestionContractError("content_length must be non-negative")
        if not _is_sha256(self.checksum_sha256):
            raise IngestionContractError("checksum_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "detected_media_type", _normalize_media_type(self.detected_media_type))


@dataclass(frozen=True)
class ResolvedAdapterConfiguration:
    adapter_key: str
    adapter_version: str
    pipeline_profile_revision: str
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.adapter_key.strip():
            raise IngestionContractError("adapter_key is required")
        if not self.adapter_version.strip():
            raise IngestionContractError("adapter_version is required")
        if not self.pipeline_profile_revision.strip():
            raise IngestionContractError("pipeline_profile_revision is required")
        object.__setattr__(self, "settings", dict(self.settings))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise IngestionContractError("validation issue code is required")
        if not self.message.strip():
            raise IngestionContractError("validation issue message is required")


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    detected_media_type: str
    issues: tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "detected_media_type", _normalize_media_type(self.detected_media_type))
        if self.accepted and self.issues:
            raise IngestionContractError("accepted validation cannot contain issues")
        if not self.accepted and not self.issues:
            raise IngestionContractError("rejected validation requires at least one issue")


@dataclass(frozen=True)
class ContentUnit:
    unit_key: str
    ordinal: int
    unit_type: IngestionUnitType
    content_hash: str
    text: str | None = None
    structured_data: Mapping[str, Any] | None = None
    source_locator: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.unit_key.strip():
            raise IngestionContractError("unit_key is required")
        if self.ordinal < 0:
            raise IngestionContractError("unit ordinal must be non-negative")
        if not _is_sha256(self.content_hash):
            raise IngestionContractError("content_hash must be a lowercase SHA-256 digest")
        if not self.text and self.structured_data is None:
            raise IngestionContractError("content unit requires text or structured_data")
        object.__setattr__(self, "source_locator", dict(self.source_locator))
        object.__setattr__(self, "attributes", dict(self.attributes))
        if self.structured_data is not None:
            object.__setattr__(self, "structured_data", dict(self.structured_data))


@dataclass(frozen=True)
class ProposedArtifact:
    artifact_type: str
    media_type: str
    content_source: str
    checksum_sha256: str
    size_bytes: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_type.strip():
            raise IngestionContractError("artifact_type is required")
        if not self.content_source.strip():
            raise IngestionContractError("content_source is required")
        if not _is_sha256(self.checksum_sha256):
            raise IngestionContractError("checksum_sha256 must be a lowercase SHA-256 digest")
        if self.size_bytes < 0:
            raise IngestionContractError("size_bytes must be non-negative")
        object.__setattr__(self, "media_type", _normalize_media_type(self.media_type))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ExtractionWarning:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise IngestionContractError("warning code and message are required")


@dataclass(frozen=True)
class ExtractionResult:
    adapter_key: str
    adapter_version: str
    detected_media_type: str
    detected_format: str
    content_units: tuple[ContentUnit, ...]
    proposed_artifacts: tuple[ProposedArtifact, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[ExtractionWarning, ...] = ()
    quality_observations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.adapter_key.strip():
            raise IngestionContractError("adapter_key is required")
        if not self.adapter_version.strip():
            raise IngestionContractError("adapter_version is required")
        if not self.detected_format.strip():
            raise IngestionContractError("detected_format is required")
        if not self.content_units:
            raise IngestionContractError("at least one content unit is required")
        unit_keys = [unit.unit_key for unit in self.content_units]
        if len(unit_keys) != len(set(unit_keys)):
            raise IngestionContractError("content unit keys must be unique")
        ordinals = [unit.ordinal for unit in self.content_units]
        if len(ordinals) != len(set(ordinals)):
            raise IngestionContractError("content unit ordinals must be unique")
        object.__setattr__(self, "detected_media_type", _normalize_media_type(self.detected_media_type))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(
            self,
            "quality_observations",
            tuple(dict(observation) for observation in self.quality_observations),
        )


@dataclass(frozen=True)
class IngestionFailure:
    error_code: str
    safe_message: str
    stage: IngestionStage
    retryable: bool
    category: IngestionErrorCategory

    def __post_init__(self) -> None:
        if not self.error_code.strip():
            raise IngestionContractError("error_code is required")
        if not self.safe_message.strip():
            raise IngestionContractError("safe_message is required")


class IngestionExecutionControl(Protocol):
    def pulse(self) -> None: ...

    def is_cancellation_requested(self) -> bool: ...

    def raise_if_cancellation_requested(self) -> None: ...


class IngestionAdapter(Protocol):
    adapter_key: str
    capabilities: AdapterCapabilities

    def validate(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
    ) -> ValidationResult: ...

    def extract(
        self,
        source: AcquiredSource,
        configuration: ResolvedAdapterConfiguration,
        control: IngestionExecutionControl,
    ) -> ExtractionResult: ...


def adapter_supports_media_type(adapter: IngestionAdapter, media_type: str) -> bool:
    return _normalize_media_type(media_type) in adapter.capabilities.supported_media_types


def select_adapter_candidates(
    adapters: Sequence[IngestionAdapter],
    media_type: str,
) -> tuple[IngestionAdapter, ...]:
    """Return deterministic capability matches without applying tenant policy.

    Persistent configuration and policy filtering remain the responsibility of the
    future adapter resolver. This helper only provides stable capability ordering.
    """

    candidates = [adapter for adapter in adapters if adapter_supports_media_type(adapter, media_type)]
    return tuple(sorted(candidates, key=lambda adapter: (adapter.capabilities.priority, adapter.adapter_key)))


def _normalize_media_type(value: str) -> str:
    normalized = value.split(";", 1)[0].strip().lower()
    if not normalized or "/" not in normalized:
        raise IngestionContractError("media type must use type/subtype form")
    return normalized


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and all(char in "0123456789abcdef" for char in value)
