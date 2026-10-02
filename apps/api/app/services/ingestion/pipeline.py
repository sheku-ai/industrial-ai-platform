from __future__ import annotations

from dataclasses import dataclass

from app.services.ingestion.adapters.contracts import (
    AdapterExecutionContext,
    ArtifactDescriptor,
    ChunkCandidate,
    ChunkingProfile,
    ExtractionAdapterResult,
    ExtractionProfile,
    IngestionSourceRef,
    QualityProfile,
)
from app.services.ingestion.adapters.interfaces import (
    ArtifactSerializationService,
    ChunkingService,
    ContentQualityService,
)
from app.services.ingestion.adapters.registry import AdapterRegistry


@dataclass(frozen=True)
class IngestionPipelineResult:
    extraction: ExtractionAdapterResult
    chunks: tuple[ChunkCandidate, ...]
    artifacts: tuple[ArtifactDescriptor, ...]


@dataclass
class IngestionPipeline:
    """Product-level ingestion orchestration boundary.

    This class defines the sequencing contract. It is not a worker daemon and it
    does not perform storage, database writes, embedding generation, or indexing.
    Later Sprint 9 packages can compose this pipeline inside the Platform Worker.
    """

    adapters: AdapterRegistry
    quality_service: ContentQualityService
    chunking_service: ChunkingService
    artifact_service: ArtifactSerializationService

    def run(
        self,
        source: IngestionSourceRef,
        extraction_profile: ExtractionProfile,
        quality_profile: QualityProfile,
        chunking_profile: ChunkingProfile,
        context: AdapterExecutionContext,
    ) -> IngestionPipelineResult:
        adapter = self.adapters.resolve(source, extraction_profile)
        extraction = adapter.extract(source, extraction_profile, context)

        accepted_blocks = tuple(
            block
            for block in extraction.blocks
            if self.quality_service.evaluate_block(block, quality_profile, context).accepted
        )

        filtered_extraction = ExtractionAdapterResult(
            source=extraction.source,
            adapter_name=extraction.adapter_name,
            adapter_version=extraction.adapter_version,
            extraction_method=extraction.extraction_method,
            blocks=accepted_blocks,
            metrics=extraction.metrics,
            diagnostics=extraction.diagnostics,
        )

        chunk_candidates = self.chunking_service.build_chunks(filtered_extraction, chunking_profile, context)
        accepted_chunks = tuple(
            chunk
            for chunk in chunk_candidates
            if self.quality_service.evaluate_chunk(chunk, quality_profile, context).accepted
        )

        artifacts = self.artifact_service.serialize_extraction(filtered_extraction, accepted_chunks, context)

        return IngestionPipelineResult(
            extraction=filtered_extraction,
            chunks=accepted_chunks,
            artifacts=artifacts,
        )
