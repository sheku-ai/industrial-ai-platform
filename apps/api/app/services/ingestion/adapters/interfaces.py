from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.ingestion.adapters.contracts import (
    AdapterCapability,
    AdapterExecutionContext,
    ArtifactDescriptor,
    ChunkCandidate,
    ChunkingProfile,
    ContentQualityDecision,
    ExtractionAdapterResult,
    ExtractionProfile,
    IngestionSourceRef,
    NormalizedContentBlock,
    QualityProfile,
)


class ExtractionAdapter(ABC):
    """Product-level boundary for extracting normalized content.

    Implementations may wrap existing technical assets in later work packages, but
    this interface is the product contract. It does not expose legacy script names,
    hardcoded collection names, document taxonomies, or customer-specific metadata.
    """

    name: str
    version: str
    capabilities: tuple[AdapterCapability, ...]

    @abstractmethod
    def supports(self, source: IngestionSourceRef, profile: ExtractionProfile) -> bool:
        """Return whether this adapter can process the source under the profile."""

    @abstractmethod
    def extract(
        self,
        source: IngestionSourceRef,
        profile: ExtractionProfile,
        context: AdapterExecutionContext,
    ) -> ExtractionAdapterResult:
        """Extract normalized content blocks from the source."""


class ContentQualityService(ABC):
    """Product-level content quality boundary."""

    @abstractmethod
    def evaluate_block(
        self,
        block: NormalizedContentBlock,
        profile: QualityProfile,
        context: AdapterExecutionContext,
    ) -> ContentQualityDecision:
        """Evaluate whether a normalized block should move forward."""

    @abstractmethod
    def evaluate_chunk(
        self,
        chunk: ChunkCandidate,
        profile: QualityProfile,
        context: AdapterExecutionContext,
    ) -> ContentQualityDecision:
        """Evaluate whether a chunk candidate should be persisted and indexed."""


class ChunkingService(ABC):
    """Product-level chunking boundary."""

    @abstractmethod
    def build_chunks(
        self,
        extraction: ExtractionAdapterResult,
        profile: ChunkingProfile,
        context: AdapterExecutionContext,
    ) -> tuple[ChunkCandidate, ...]:
        """Build deterministic chunk candidates from normalized content blocks."""


class ArtifactSerializationService(ABC):
    """Product-level artifact serialization boundary."""

    @abstractmethod
    def serialize_extraction(
        self,
        extraction: ExtractionAdapterResult,
        chunks: tuple[ChunkCandidate, ...],
        context: AdapterExecutionContext,
    ) -> tuple[ArtifactDescriptor, ...]:
        """Serialize extraction outputs and chunk artifacts."""
