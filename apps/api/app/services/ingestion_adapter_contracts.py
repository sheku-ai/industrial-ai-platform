from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class AdapterKind(StrEnum):
    TEXT = "text"
    RICH_DOCUMENT = "rich_document"
    SPREADSHEET = "spreadsheet"
    NDJSON = "ndjson"


class AdapterCapability(StrEnum):
    EXTRACT_TEXT = "extract_text"
    EXTRACT_STRUCTURE = "extract_structure"
    PRESERVE_PAGE_PROVENANCE = "preserve_page_provenance"
    PRESERVE_TABULAR_PROVENANCE = "preserve_tabular_provenance"
    LOAD_CHUNKS = "load_chunks"
    OPTIONAL_OCR = "optional_ocr"


class AdapterCoupling(StrEnum):
    DATABASE = "database"
    OBJECT_STORAGE = "object_storage"
    VECTOR_STORE = "vector_store"
    EMBEDDING_PROVIDER = "embedding_provider"
    LOCAL_FILESYSTEM = "local_filesystem"
    EXTERNAL_BINARY = "external_binary"


class AdapterExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYABLE = "retryable"


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_key: str
    kind: AdapterKind
    supported_extensions: tuple[str, ...]
    supported_media_types: tuple[str, ...]
    capabilities: frozenset[AdapterCapability]
    implementation_asset: str
    direct_couplings: frozenset[AdapterCoupling] = frozenset()
    enabled_by_default: bool = False
    requires_ai: bool = False

    def __post_init__(self) -> None:
        if not self.adapter_key or self.adapter_key != self.adapter_key.strip().lower():
            raise ValueError("adapter_key must be a lowercase stable identifier")
        if not self.supported_extensions and not self.supported_media_types:
            raise ValueError("adapter must declare at least one routable input")
        if self.requires_ai:
            raise ValueError("ingestion adapter contracts must not require AI")


@dataclass(frozen=True)
class AdapterInput:
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_reference: str
    original_file_name: str
    declared_media_type: str | None
    checksum_sha256: str
    content_length: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    attempt: int = 1

    def __post_init__(self) -> None:
        if not self.source_reference:
            raise ValueError("source_reference is required")
        if not self.original_file_name:
            raise ValueError("original_file_name is required")
        if len(self.checksum_sha256) != 64:
            raise ValueError("checksum_sha256 must be a SHA-256 hexadecimal digest")
        if self.content_length < 0:
            raise ValueError("content_length cannot be negative")
        if self.attempt < 1:
            raise ValueError("attempt must be at least one")


@dataclass(frozen=True)
class AdapterArtifact:
    artifact_type: str
    media_type: str
    relative_path: str
    checksum_sha256: str
    size_bytes: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterChunk:
    chunk_index: int
    text: str
    content_type: str = "text/plain"
    section_ref: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index cannot be negative")
        if not self.text.strip():
            raise ValueError("chunk text cannot be empty")


@dataclass(frozen=True)
class AdapterExecutionResult:
    status: AdapterExecutionStatus
    chunks: tuple[AdapterChunk, ...] = ()
    artifacts: tuple[AdapterArtifact, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.status == AdapterExecutionStatus.SUCCEEDED and self.error_code:
            raise ValueError("successful result cannot include an error_code")
        if self.status != AdapterExecutionStatus.SUCCEEDED and not self.error_code:
            raise ValueError("failed or retryable result requires an error_code")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds cannot be negative")


class IngestionAdapter(Protocol):
    descriptor: AdapterDescriptor

    def execute(self, request: AdapterInput) -> AdapterExecutionResult: ...


@dataclass(frozen=True)
class AdapterRouteDecision:
    adapter_key: str
    reason: str


class AdapterRoutingError(ValueError):
    pass


def normalize_extension(file_name: str) -> str:
    lowered = file_name.strip().lower()
    if "." not in lowered:
        return ""
    return "." + lowered.rsplit(".", 1)[1]


def select_adapter(
    descriptors: Sequence[AdapterDescriptor],
    *,
    file_name: str,
    declared_media_type: str | None,
) -> AdapterRouteDecision:
    extension = normalize_extension(file_name)
    media_type = (declared_media_type or "").strip().lower()
    matches: list[tuple[AdapterDescriptor, str]] = []

    for descriptor in descriptors:
        extension_match = extension and extension in descriptor.supported_extensions
        media_match = media_type and media_type in descriptor.supported_media_types
        if extension_match or media_match:
            reason = (
                "extension_and_media_type"
                if extension_match and media_match
                else "extension"
                if extension_match
                else "media_type"
            )
            matches.append((descriptor, reason))

    if not matches:
        raise AdapterRoutingError("no configured ingestion adapter matches the input")

    unique_keys = {descriptor.adapter_key for descriptor, _ in matches}
    if len(unique_keys) > 1:
        raise AdapterRoutingError("input matches multiple configured ingestion adapters")

    descriptor, reason = matches[0]
    return AdapterRouteDecision(adapter_key=descriptor.adapter_key, reason=reason)


BUILTIN_ADAPTER_INVENTORY: tuple[AdapterDescriptor, ...] = (
    AdapterDescriptor(
        adapter_key="text",
        kind=AdapterKind.TEXT,
        supported_extensions=(".txt", ".md", ".html", ".htm", ".xml", ".json"),
        supported_media_types=("text/plain", "text/markdown", "text/html", "application/xml", "application/json"),
        capabilities=frozenset({AdapterCapability.EXTRACT_TEXT}),
        implementation_asset="worker_ingest_text.py",
        direct_couplings=frozenset({AdapterCoupling.LOCAL_FILESYSTEM}),
    ),
    AdapterDescriptor(
        adapter_key="rich-document",
        kind=AdapterKind.RICH_DOCUMENT,
        supported_extensions=(".pdf", ".docx", ".pptx", ".eml", ".msg", ".png", ".jpg", ".jpeg", ".tif", ".tiff"),
        supported_media_types=("application/pdf",),
        capabilities=frozenset(
            {AdapterCapability.EXTRACT_TEXT, AdapterCapability.PRESERVE_PAGE_PROVENANCE, AdapterCapability.OPTIONAL_OCR}
        ),
        implementation_asset="worker_ingest_pdf.py",
        direct_couplings=frozenset({AdapterCoupling.LOCAL_FILESYSTEM, AdapterCoupling.EXTERNAL_BINARY}),
    ),
    AdapterDescriptor(
        adapter_key="spreadsheet",
        kind=AdapterKind.SPREADSHEET,
        supported_extensions=(".xlsx", ".xls", ".csv"),
        supported_media_types=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "text/csv",
        ),
        capabilities=frozenset({AdapterCapability.EXTRACT_STRUCTURE, AdapterCapability.PRESERVE_TABULAR_PROVENANCE}),
        implementation_asset="worker_ingest_excel.py",
        direct_couplings=frozenset({AdapterCoupling.LOCAL_FILESYSTEM}),
    ),
    AdapterDescriptor(
        adapter_key="ndjson",
        kind=AdapterKind.NDJSON,
        supported_extensions=(".ndjson",),
        supported_media_types=("application/x-ndjson",),
        capabilities=frozenset({AdapterCapability.LOAD_CHUNKS}),
        implementation_asset="worker_load_chunks_ndjson.py",
        direct_couplings=frozenset(
            {
                AdapterCoupling.DATABASE,
                AdapterCoupling.VECTOR_STORE,
                AdapterCoupling.EMBEDDING_PROVIDER,
                AdapterCoupling.LOCAL_FILESYSTEM,
            }
        ),
    ),
)
