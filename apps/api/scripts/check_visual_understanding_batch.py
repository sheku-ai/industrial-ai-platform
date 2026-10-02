import io
import json
import tempfile
import time
from dataclasses import replace

from PIL import Image, ImageDraw

from app.services.embedded_image_builder import EmbeddedImageBuilder
from app.services.embedded_image_extraction import EmbeddedImageExtractionResult
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    CapabilityState,
    MultimodalStatus,
    ProcessingProfile,
    ProviderCapability,
    VisualDescription,
    VisualUnderstandingRequest,
)
from app.services.visual_understanding import (
    DeterministicLocalVisualProvider,
    VisualUnderstandingCache,
    VisualUnderstandingService,
)
from app.services.visual_understanding_batch import VisualUnderstandingBatchProcessor


def image_bytes(width, height, marker):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, width - 5, height - 5), outline="black", width=2)
    draw.text((8, 8), marker, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class UnavailableProvider:
    capability = ProviderCapability(
        provider_key="unavailable-local-vision",
        capability="image_understanding",
        state=CapabilityState.UNAVAILABLE,
        version="0",
        local=True,
    )

    def describe(self, image, payload, *, request):
        raise AssertionError("unavailable provider must not execute")


class SlowProvider:
    capability = ProviderCapability(
        provider_key="slow-local-vision",
        capability="image_understanding",
        state=CapabilityState.AVAILABLE,
        version="1",
        local=True,
    )

    def describe(self, image, payload, *, request):
        time.sleep(0.2)
        return VisualDescription(status=MultimodalStatus.SUCCEEDED)


def main():
    builder = EmbeddedImageBuilder()
    primary_payload = image_bytes(320, 180, "primary")
    primary = builder.build(
        primary_payload,
        content_type="image/png",
        source_kind="pptx",
        source_locator={"slide_number": 2},
        metadata={"container_width": 320, "container_height": 180},
    )
    duplicate = builder.build(
        primary_payload,
        content_type="image/png",
        source_kind="docx",
        source_locator={"section_index": 4},
    )
    small = builder.build(
        image_bytes(40, 40, "s"),
        content_type="image/png",
        source_kind="pdf",
        source_locator={"page_number": 7},
        metadata={"container_width": 1000, "container_height": 1000},
    )
    assert primary and duplicate and small

    extraction = EmbeddedImageExtractionResult(
        occurrences=(primary, duplicate, small),
        unique_image_count=2,
        duplicate_count=1,
    )
    request = VisualUnderstandingRequest(
        profile=ProcessingProfile.BALANCED,
        prompt="Describe observable structure.",
        configuration={"mode": "deterministic"},
        timeout_seconds=1,
    )
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]

    with tempfile.TemporaryDirectory(prefix="visual-batch-smoke-") as cache_dir:
        processor = VisualUnderstandingBatchProcessor(
            VisualUnderstandingService(
                DeterministicLocalVisualProvider(),
                cache=VisualUnderstandingCache(cache_dir),
            )
        )
        batch = processor.enrich(extraction, policy=policy, request=request)

    unavailable = VisualUnderstandingService(UnavailableProvider()).enrich(
        primary,
        policy=policy,
        request=request,
    )
    timeout_request = replace(request, timeout_seconds=0.01)
    timeout = VisualUnderstandingService(SlowProvider()).enrich(
        primary,
        policy=policy,
        request=timeout_request,
    )

    {next(iter(item.source_locator.keys())): item for item in batch.items}
    small_item = next(item for item in batch.items if item.image_hash == small.image.image_hash)
    duplicate_item = next(item for item in batch.items if item.duplicate_of is not None)
    primary_item = next(
        item for item in batch.items if item.image_hash == primary.image.image_hash and item.duplicate_of is None
    )

    checks = {
        "batch_partial_not_blocking": batch.status == MultimodalStatus.PARTIAL,
        "all_occurrences_reported": len(batch.items) == 3,
        "primary_succeeded": primary_item.result.status == MultimodalStatus.SUCCEEDED,
        "duplicate_excluded": duplicate_item.result.metrics.get("skip_reason") == "duplicate_image",
        "small_excluded_by_ratio": small_item.result.metrics.get("skip_reason") == "below_minimum_image_area_ratio",
        "provenance_preserved": (
            primary_item.source_locator.get("slide_number") == 2
            and duplicate_item.source_locator.get("section_index") == 4
            and small_item.source_locator.get("page_number") == 7
        ),
        "batch_metrics": (
            batch.metrics.get("total_occurrences") == 3
            and batch.metrics.get("unique_images") == 2
            and batch.metrics.get("duplicates") == 1
            and batch.metrics.get("succeeded") == 1
            and batch.metrics.get("skipped") == 2
        ),
        "unavailable_degraded": (
            unavailable.status == MultimodalStatus.PARTIAL and unavailable.error_code == "provider_unavailable"
        ),
        "timeout_degraded": (
            timeout.status == MultimodalStatus.PARTIAL and timeout.error_code == "visual_provider_timeout"
        ),
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "batch_status": batch.status.value, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
