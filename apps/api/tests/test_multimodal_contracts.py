from uuid import uuid4

import pytest

from app.services.multimodal_contracts import (
    DEFAULT_PROCESSING_POLICIES,
    CapabilityState,
    DocumentExtractionRequest,
    ExtractedImage,
    ProcessingPolicy,
    ProcessingProfile,
    ProviderCapability,
    ResourceBudget,
    VisualContentPolicy,
    VisualContentType,
)


def test_default_profiles_preserve_non_mandatory_network_and_ai() -> None:
    economy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.ECONOMY]
    balanced = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]
    offline = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.OFFLINE_STRICT]

    assert economy.enable_ocr is True
    assert economy.enable_visual_understanding is False
    assert economy.allow_network is False
    assert balanced.enable_visual_understanding is True
    assert balanced.allow_network is False
    assert offline.require_local_providers is True
    assert offline.allow_network is False


def test_resource_budget_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ResourceBudget(max_images=-1)

    with pytest.raises(ValueError, match="at least one"):
        ResourceBudget(max_attempts=0)


def test_local_only_policy_cannot_allow_network() -> None:
    with pytest.raises(ValueError, match="cannot allow network"):
        ProcessingPolicy(
            profile=ProcessingProfile.OFFLINE_STRICT,
            enable_ocr=True,
            enable_visual_understanding=True,
            allow_network=True,
            require_local_providers=True,
            minimum_text_chars_per_page=100,
            minimum_image_area_ratio=0.05,
            budget=ResourceBudget(),
        )


def test_visual_policy_skips_duplicates_and_logos() -> None:
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]
    evaluator = VisualContentPolicy()
    image = ExtractedImage(
        image_id="img-1",
        image_hash="abc",
        content_type="image/png",
        width=800,
        height=600,
        content_type_classification=VisualContentType.LOGO,
    )

    duplicate = evaluator.decide(policy=policy, image=image, text_chars_on_page=0, duplicate_image=True)
    logo = evaluator.decide(policy=policy, image=image, text_chars_on_page=0, duplicate_image=False)

    assert duplicate.reason == "duplicate_image"
    assert logo.reason == "non_informative_image"
    assert duplicate.run_ocr is False
    assert logo.run_visual_understanding is False


def test_visual_policy_uses_ocr_for_scanned_text() -> None:
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.ECONOMY]
    image = ExtractedImage(
        image_id="img-2",
        image_hash="def",
        content_type="image/tiff",
        width=1600,
        height=2400,
        content_type_classification=VisualContentType.SCANNED_TEXT,
    )

    decision = VisualContentPolicy().decide(
        policy=policy,
        image=image,
        text_chars_on_page=0,
        duplicate_image=False,
    )

    assert decision.run_ocr is True
    assert decision.run_visual_understanding is False
    assert decision.reason == "ocr_relevant"


def test_balanced_profile_describes_diagrams_without_forcing_ocr() -> None:
    policy = DEFAULT_PROCESSING_POLICIES[ProcessingProfile.BALANCED]
    image = ExtractedImage(
        image_id="img-3",
        image_hash="ghi",
        content_type="image/png",
        width=1200,
        height=800,
        content_type_classification=VisualContentType.DIAGRAM,
    )

    decision = VisualContentPolicy().decide(
        policy=policy,
        image=image,
        text_chars_on_page=500,
        duplicate_image=False,
    )

    assert decision.run_ocr is False
    assert decision.run_visual_understanding is True
    assert decision.reason == "visual_relevant"


def test_provider_capability_can_report_disabled_without_failure() -> None:
    capability = ProviderCapability(
        provider_key="vision-local",
        capability="image_understanding",
        state=CapabilityState.DISABLED,
        local=True,
        requires_gpu=True,
    )

    assert capability.state == CapabilityState.DISABLED
    assert capability.requires_gpu is True


def test_document_request_remains_generic() -> None:
    request = DocumentExtractionRequest(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_reference="s3://bucket/object",
        original_file_name="document.pdf",
        declared_media_type="application/pdf",
        checksum_sha256="a" * 64,
        profile=ProcessingProfile.ECONOMY,
        policy=DEFAULT_PROCESSING_POLICIES[ProcessingProfile.ECONOMY],
    )

    assert request.metadata == {}
    assert request.policy.profile == ProcessingProfile.ECONOMY
