import io
import json
from dataclasses import replace

from PIL import Image, ImageDraw

from app.services.embedded_image_builder import EmbeddedImageBuilder
from app.services.embedded_image_extraction import EmbeddedImageExtractionResult
from app.services.embedded_image_visual_pipeline import EmbeddedImageVisualPipeline
from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    MultimodalStatus,
    ProcessingProfile,
    VisualUnderstandingRequest,
)
from app.services.visual_understanding import (
    DeterministicLocalVisualProvider,
    VisualUnderstandingService,
)
from app.services.visual_understanding_batch import VisualUnderstandingBatchProcessor


def image_bytes():
    image = Image.new("RGB", (300, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 280, 160), outline="black", width=4)
    draw.line((30, 140, 150, 40, 270, 120), fill="black", width=4)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class DeterministicExtractionFixture:
    def extract(self, payload: bytes, **kwargs):
        builder = EmbeddedImageBuilder()
        primary = builder.build(
            payload,
            content_type="image/png",
            source_kind="pptx",
            source_locator={"slide_number": 1},
            metadata={"relationship_id": "rId1"},
        )
        duplicate = builder.build(
            payload,
            content_type="image/png",
            source_kind="pptx",
            source_locator={"slide_number": 2},
            metadata={"relationship_id": "rId2"},
        )
        assert primary is not None and duplicate is not None
        return EmbeddedImageExtractionResult(
            occurrences=(primary, duplicate),
            unique_image_count=1,
            duplicate_count=1,
        )


def main():
    payload = image_bytes()
    request = VisualUnderstandingRequest(
        profile=ProcessingProfile.BALANCED,
        prompt="Describe observable visual structure.",
        configuration={"mode": "pipeline-smoke"},
        timeout_seconds=2,
    )
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]

    pipeline = EmbeddedImageVisualPipeline(
        DeterministicExtractionFixture(),
        batch_processor=VisualUnderstandingBatchProcessor(
            VisualUnderstandingService(DeterministicLocalVisualProvider())
        ),
    )
    integrated = pipeline.run(payload, policy=policy, request=request)
    disabled = pipeline.run(
        payload,
        policy=replace(policy, enable_visual_understanding=False),
        request=request,
    )

    artifact = integrated.artifact or {}
    items = artifact.get("items") or []
    serialized = json.dumps(artifact, sort_keys=True)
    checks = {
        "extraction_preserved": (
            len(integrated.extraction.occurrences) == 2
            and integrated.extraction.unique_image_count == 1
            and integrated.extraction.duplicate_count == 1
        ),
        "enrichment_executed": integrated.metrics.get("visual_enrichment_executed") is True,
        "combined_partial": integrated.status == MultimodalStatus.PARTIAL,
        "artifact_schema": artifact.get("schema") == "visual-enrichment/v1",
        "artifact_serializable": json.loads(serialized) == artifact,
        "artifact_occurrences": len(items) == 2,
        "artifact_traceability": all(
            item.get("image_hash")
            and item.get("source_kind") == "pptx"
            and item.get("source_locator", {}).get("slide_number") in {1, 2}
            and item.get("visual", {}).get("provider_key") == "deterministic-local-vision"
            for item in items
        ),
        "duplicate_not_reprocessed": sum(
            1 for item in items if item.get("visual", {}).get("metrics", {}).get("skip_reason") == "duplicate_image"
        )
        == 1,
        "disabled_extraction_still_available": (
            disabled.status == MultimodalStatus.SUCCEEDED
            and len(disabled.extraction.occurrences) == 2
            and disabled.enrichment is None
            and disabled.artifact is None
            and disabled.metrics.get("visual_enrichment_reason") == "visual_understanding_disabled"
        ),
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {"passed": passed, "integrated_status": integrated.status.value, **checks},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
