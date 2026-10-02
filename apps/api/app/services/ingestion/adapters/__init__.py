"""Generic ingestion adapter interfaces and contracts.

This package defines product-level adapter boundaries. It must not import legacy
worker scripts directly. Historical implementation assets may be wrapped behind
these interfaces in later Sprint 9 work packages.
"""

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
from app.services.ingestion.adapters.interfaces import (
    ArtifactSerializationService,
    ChunkingService,
    ContentQualityService,
    ExtractionAdapter,
)
from app.services.ingestion.adapters.registry import AdapterRegistry

__all__ = [
    "AdapterCapability",
    "AdapterExecutionContext",
    "ArtifactDescriptor",
    "ChunkCandidate",
    "ChunkingProfile",
    "ContentQualityDecision",
    "ExtractionAdapterResult",
    "ExtractionProfile",
    "IngestionSourceRef",
    "NormalizedContentBlock",
    "QualityProfile",
    "ArtifactSerializationService",
    "ChunkingService",
    "ContentQualityService",
    "ExtractionAdapter",
    "AdapterRegistry",
]
