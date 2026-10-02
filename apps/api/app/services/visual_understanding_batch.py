from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.embedded_image_extraction import (
    EmbeddedImageExtractionResult,
    EmbeddedImageOccurrence,
)
from app.services.multimodal_contracts import (
    MultimodalStatus,
    ProcessingPolicy,
    VisualDescription,
    VisualUnderstandingRequest,
)
from app.services.visual_understanding import VisualUnderstandingService


@dataclass(frozen=True)
class VisualEnrichmentItem:
    image_id: str
    image_hash: str
    source_kind: str
    source_locator: Mapping[str, Any]
    duplicate_of: str | None
    result: VisualDescription


@dataclass(frozen=True)
class VisualEnrichmentBatchResult:
    status: MultimodalStatus
    items: tuple[VisualEnrichmentItem, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class VisualUnderstandingBatchProcessor:
    """Applies optional visual enrichment to one isolated extraction batch."""

    def __init__(self, service: VisualUnderstandingService) -> None:
        self.service = service

    def fork(self) -> VisualUnderstandingBatchProcessor:
        """Create an execution-local processor while preserving provider configuration and cache."""
        return VisualUnderstandingBatchProcessor(
            VisualUnderstandingService(
                self.service.provider,
                cache=self.service.cache,
                content_policy=self.service.content_policy,
            )
        )

    def enrich(
        self,
        extraction: EmbeddedImageExtractionResult,
        *,
        policy: ProcessingPolicy,
        request: VisualUnderstandingRequest,
        text_chars_by_locator: Mapping[str, int] | None = None,
    ) -> VisualEnrichmentBatchResult:
        text_chars_by_locator = text_chars_by_locator or {}
        items: list[VisualEnrichmentItem] = []
        counts = {
            "total_occurrences": len(extraction.occurrences),
            "unique_images": extraction.unique_image_count,
            "duplicates": extraction.duplicate_count,
            "extraction_skipped": extraction.skipped_count,
            "succeeded": 0,
            "partial": 0,
            "skipped": 0,
            "failed": 0,
            "cache_hits": 0,
        }
        warning_set: set[str] = set()

        for occurrence in extraction.occurrences:
            precheck_reason = self._precheck(occurrence, policy)
            if precheck_reason:
                result = self.service.enrich(
                    _as_skipped_duplicate(occurrence),
                    policy=policy,
                    request=request,
                    text_chars_on_page=0,
                )
                result = VisualDescription(
                    **{
                        **result.__dict__,
                        "warnings": tuple(dict.fromkeys((*result.warnings, precheck_reason))),
                        "metrics": {
                            **dict(result.metrics),
                            "skip_reason": precheck_reason,
                        },
                    }
                )
            else:
                locator_key = stable_locator_key(occurrence)
                result = self.service.enrich(
                    occurrence,
                    policy=policy,
                    request=request,
                    text_chars_on_page=int(text_chars_by_locator.get(locator_key, 0)),
                )

            counts[result.status.value] = counts.get(result.status.value, 0) + 1
            if result.metrics.get("cache_hit") is True:
                counts["cache_hits"] += 1
            warning_set.update(result.warnings)
            items.append(
                VisualEnrichmentItem(
                    image_id=occurrence.image.image_id,
                    image_hash=occurrence.image.image_hash,
                    source_kind=occurrence.source_kind,
                    source_locator=dict(occurrence.source_locator),
                    duplicate_of=occurrence.duplicate_of,
                    result=result,
                )
            )

        status = _batch_status(items)
        return VisualEnrichmentBatchResult(
            status=status,
            items=tuple(items),
            metrics=counts,
            warnings=tuple(sorted(warning_set)),
        )

    @staticmethod
    def _precheck(
        occurrence: EmbeddedImageOccurrence,
        policy: ProcessingPolicy,
    ) -> str | None:
        if occurrence.duplicate_of:
            return "duplicate_image"

        metadata = occurrence.image.metadata
        container_width = _positive_number(metadata.get("container_width"))
        container_height = _positive_number(metadata.get("container_height"))
        if container_width and container_height:
            image_area = occurrence.image.width * occurrence.image.height
            container_area = container_width * container_height
            area_ratio = image_area / container_area
            if area_ratio < policy.minimum_image_area_ratio:
                return "below_minimum_image_area_ratio"

        return None


def stable_locator_key(occurrence: EmbeddedImageOccurrence) -> str:
    locator = occurrence.source_locator
    if occurrence.image.page is not None:
        return f"page:{occurrence.image.page}"
    if occurrence.image.slide is not None:
        return f"slide:{occurrence.image.slide}"
    if occurrence.image.sheet:
        return f"sheet:{occurrence.image.sheet}"
    for key in ("page_number", "slide_number", "section_index", "mime_part_index"):
        if key in locator:
            return f"{key}:{locator[key]}"
    return f"image:{occurrence.image.image_id}"


def _positive_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_skipped_duplicate(occurrence: EmbeddedImageOccurrence) -> EmbeddedImageOccurrence:
    if occurrence.duplicate_of:
        return occurrence
    return EmbeddedImageOccurrence(
        image=occurrence.image,
        payload=occurrence.payload,
        source_kind=occurrence.source_kind,
        source_locator=occurrence.source_locator,
        duplicate_of="policy-skip",
    )


def _batch_status(items: Sequence[VisualEnrichmentItem]) -> MultimodalStatus:
    if not items:
        return MultimodalStatus.SKIPPED
    statuses = {item.result.status for item in items}
    if statuses == {MultimodalStatus.SUCCEEDED}:
        return MultimodalStatus.SUCCEEDED
    if MultimodalStatus.SUCCEEDED in statuses or MultimodalStatus.PARTIAL in statuses:
        return MultimodalStatus.PARTIAL
    if statuses == {MultimodalStatus.FAILED}:
        return MultimodalStatus.FAILED
    return MultimodalStatus.SKIPPED
