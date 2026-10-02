import io
import json
import tempfile
from dataclasses import replace

from PIL import Image, ImageDraw

from app.services.embedded_image_builder import EmbeddedImageBuilder
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    CapabilityState,
    MultimodalStatus,
    ProcessingProfile,
    VisualUnderstandingRequest,
)
from app.services.visual_understanding import (
    DeterministicLocalVisualProvider,
    VisualUnderstandingCache,
    VisualUnderstandingService,
)


def image_bytes(width=320, height=180):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, width - 20, height - 20), outline="black", width=4)
    draw.line((30, height - 40, width // 2, 40, width - 30, height - 60), fill="black", width=4)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def main():
    payload = image_bytes()
    builder = EmbeddedImageBuilder()
    occurrence = builder.build(
        payload,
        content_type="image/png",
        source_kind="pptx",
        source_locator={"slide_number": 3},
        metadata={"relationship_id": "rId7"},
    )
    duplicate = builder.build(
        payload,
        content_type="image/png",
        source_kind="docx",
        source_locator={"section_index": 2},
    )
    assert occurrence is not None and duplicate is not None

    request = VisualUnderstandingRequest(
        profile=ProcessingProfile.BALANCED,
        prompt="Describe observable visual structure.",
        configuration={"caption_style": "concise"},
        timeout_seconds=2,
    )
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]

    with tempfile.TemporaryDirectory(prefix="visual-understanding-smoke-") as cache_dir:
        cache = VisualUnderstandingCache(cache_dir)
        first_service = VisualUnderstandingService(DeterministicLocalVisualProvider(), cache=cache)
        first = first_service.enrich(occurrence, policy=policy, request=request)
        duplicate_result = first_service.enrich(duplicate, policy=policy, request=request)

        second_service = VisualUnderstandingService(DeterministicLocalVisualProvider(), cache=cache)
        cached = second_service.enrich(occurrence, policy=policy, request=request)

        disabled_policy = replace(policy, enable_visual_understanding=False)
        disabled = VisualUnderstandingService(DeterministicLocalVisualProvider()).enrich(
            occurrence,
            policy=disabled_policy,
            request=request,
        )

        checks = {
            "provider_available": first_service.capability().state == CapabilityState.AVAILABLE,
            "structured_result": (
                first.status == MultimodalStatus.SUCCEEDED
                and bool(first.caption)
                and bool(first.description)
                and bool(first.labels)
                and first.confidence is not None
                and bool(first.warnings)
                and bool(first.metrics)
            ),
            "provider_traceability": (
                first.provider_key == "deterministic-local-vision"
                and first.provider_version == "1.0"
                and first.profile == ProcessingProfile.BALANCED
                and bool(first.configuration_fingerprint)
            ),
            "provenance_preserved": (
                occurrence.image.image_hash == duplicate.image.image_hash
                and occurrence.source_locator.get("slide_number") == 3
                and occurrence.image.metadata.get("relationship_id") == "rId7"
            ),
            "duplicate_skipped": (
                duplicate_result.status == MultimodalStatus.SKIPPED
                and duplicate_result.metrics.get("skip_reason") == "duplicate_image"
            ),
            "cache_hit": cached.status == MultimodalStatus.SUCCEEDED and cached.metrics.get("cache_hit") is True,
            "disabled_safe": (
                disabled.status == MultimodalStatus.SKIPPED
                and disabled.metrics.get("skip_reason") == "visual_understanding_disabled"
            ),
            "offline_local": first_service.capability().local is True,
        }

    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "image_hash": occurrence.image.image_hash,
                "classification": first.classification.value,
                "caption": first.caption,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
