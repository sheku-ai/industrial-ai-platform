from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.services.embedded_image_extraction import (
    EmbeddedImageExtractionResult,
    EmbeddedImageExtractor,
)
from app.services.multimodal_contracts import (
    MultimodalStatus,
    ProcessingPolicy,
    VisualUnderstandingRequest,
)
from app.services.visual_enrichment_artifacts import serialize_visual_enrichment_batch
from app.services.visual_understanding_batch import (
    VisualEnrichmentBatchResult,
    VisualUnderstandingBatchProcessor,
)


@dataclass(frozen=True)
class EmbeddedImageVisualPipelineResult:
    extraction: EmbeddedImageExtractionResult
    enrichment: VisualEnrichmentBatchResult | None
    artifact: Mapping[str, Any] | None
    status: MultimodalStatus
    metrics: Mapping[str, Any] = field(default_factory=dict)


class EmbeddedImageVisualPipeline:
    """Composes image extraction with execution-isolated visual enrichment."""

    def __init__(
        self,
        extractor: EmbeddedImageExtractor,
        *,
        batch_processor: VisualUnderstandingBatchProcessor | None = None,
    ) -> None:
        self.extractor = extractor
        self.batch_processor = batch_processor

    def run(
        self,
        payload: bytes,
        *,
        policy: ProcessingPolicy,
        request: VisualUnderstandingRequest,
        extractor_kwargs: Mapping[str, Any] | None = None,
        text_chars_by_locator: Mapping[str, int] | None = None,
    ) -> EmbeddedImageVisualPipelineResult:
        extraction = self.extractor.extract(payload, **dict(extractor_kwargs or {}))

        if not policy.enable_visual_understanding or self.batch_processor is None:
            reason = (
                "visual_understanding_disabled"
                if not policy.enable_visual_understanding
                else "visual_batch_processor_unconfigured"
            )
            return EmbeddedImageVisualPipelineResult(
                extraction=extraction,
                enrichment=None,
                artifact=None,
                status=MultimodalStatus.SUCCEEDED,
                metrics={
                    "extraction_occurrences": len(extraction.occurrences),
                    "visual_enrichment_executed": False,
                    "visual_enrichment_reason": reason,
                },
            )

        processor = self.batch_processor.fork()
        enrichment = processor.enrich(
            extraction,
            policy=policy,
            request=request,
            text_chars_by_locator=text_chars_by_locator,
        )
        artifact = serialize_visual_enrichment_batch(
            enrichment,
            extraction_metrics={
                "occurrences": len(extraction.occurrences),
                "unique_images": extraction.unique_image_count,
                "duplicates": extraction.duplicate_count,
                "skipped": extraction.skipped_count,
            },
        )

        return EmbeddedImageVisualPipelineResult(
            extraction=extraction,
            enrichment=enrichment,
            artifact=artifact,
            status=_combined_status(extraction, enrichment),
            metrics={
                "extraction_occurrences": len(extraction.occurrences),
                "visual_enrichment_executed": True,
                "visual_status": enrichment.status.value,
            },
        )


def _combined_status(
    extraction: EmbeddedImageExtractionResult,
    enrichment: VisualEnrichmentBatchResult,
) -> MultimodalStatus:
    if not extraction.occurrences:
        return MultimodalStatus.SKIPPED
    if enrichment.status == MultimodalStatus.FAILED:
        return MultimodalStatus.PARTIAL
    if enrichment.status == MultimodalStatus.PARTIAL:
        return MultimodalStatus.PARTIAL
    return MultimodalStatus.SUCCEEDED
