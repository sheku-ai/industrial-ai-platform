import json
from dataclasses import replace

from app.services.embedded_image_visual_pipeline import EmbeddedImageVisualPipeline
from app.services.multimodal_contracts import DEFAULT_PROCESSING_POLICIES, ProcessingProfile, VisualUnderstandingRequest
from app.services.ooxml_embedded_image_extractor import OoxmlEmbeddedImageExtractor
from app.services.visual_understanding import DeterministicLocalVisualProvider, VisualUnderstandingService
from app.services.visual_understanding_batch import VisualUnderstandingBatchProcessor
from scripts.check_worker_visual_enrichment_producer_e2e_v2 import build_docx


def main():
    payload = build_docx()
    profile = ProcessingProfile.BALANCED
    policy = replace(DEFAULT_PROCESSING_POLICIES[profile], enable_visual_understanding=True)
    request = VisualUnderstandingRequest(
        profile=profile,
        prompt="Describe observable image properties.",
        configuration={},
        timeout_seconds=10.0,
    )
    pipeline = EmbeddedImageVisualPipeline(
        OoxmlEmbeddedImageExtractor(),
        batch_processor=VisualUnderstandingBatchProcessor(
            VisualUnderstandingService(DeterministicLocalVisualProvider())
        ),
    )

    first = pipeline.run(payload, policy=policy, request=request, extractor_kwargs={"source_kind": "docx"})
    second = pipeline.run(payload, policy=policy, request=request, extractor_kwargs={"source_kind": "docx"})
    first_item = first.enrichment.items[0]
    second_item = second.enrichment.items[0]

    checks = {
        "first_succeeded": first_item.result.status.value == "succeeded",
        "second_succeeded": second_item.result.status.value == "succeeded",
        "same_image_hash": first_item.image_hash == second_item.image_hash,
        "first_not_duplicate": first_item.duplicate_of is None,
        "second_not_duplicate": second_item.duplicate_of is None,
        "second_not_skipped_by_prior_execution": second_item.result.metrics.get("skip_reason") != "duplicate_image",
        "provider_preserved": second_item.result.provider_key == "deterministic-local-vision",
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "image_hash": first_item.image_hash, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
