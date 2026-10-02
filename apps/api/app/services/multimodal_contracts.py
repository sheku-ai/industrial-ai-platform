from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    DEGRADED = "degraded"


class ProcessingProfile(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    HIGH_FIDELITY = "high_fidelity"
    OFFLINE_STRICT = "offline_strict"


class VisualContentType(StrEnum):
    DECORATIVE = "decorative"
    LOGO = "logo"
    PHOTOGRAPH = "photograph"
    DIAGRAM = "diagram"
    CHART = "chart"
    TABLE = "table"
    SCREENSHOT = "screenshot"
    SCANNED_TEXT = "scanned_text"
    HANDWRITING = "handwriting"
    UNKNOWN = "unknown"


class ExtractionStage(StrEnum):
    PRIMARY = "primary"
    OCR = "ocr"
    VISUAL_UNDERSTANDING = "visual_understanding"
    FUSION = "fusion"


class MultimodalStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYABLE = "retryable"


@dataclass(frozen=True)
class ResourceBudget:
    max_source_bytes: int = 100 * 1024 * 1024
    max_pages: int = 500
    max_images: int = 100
    max_ocr_pages: int = 50
    max_visual_images: int = 20
    timeout_seconds: int = 300
    max_attempts: int = 3

    def __post_init__(self) -> None:
        values = (
            self.max_source_bytes,
            self.max_pages,
            self.max_images,
            self.max_ocr_pages,
            self.max_visual_images,
            self.timeout_seconds,
            self.max_attempts,
        )
        if any(value < 0 for value in values):
            raise ValueError("resource budget values cannot be negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")


@dataclass(frozen=True)
class ProcessingPolicy:
    profile: ProcessingProfile
    enable_ocr: bool
    enable_visual_understanding: bool
    allow_network: bool
    require_local_providers: bool
    minimum_text_chars_per_page: int
    minimum_image_area_ratio: float
    budget: ResourceBudget

    def __post_init__(self) -> None:
        if self.minimum_text_chars_per_page < 0:
            raise ValueError("minimum_text_chars_per_page cannot be negative")
        if not 0 <= self.minimum_image_area_ratio <= 1:
            raise ValueError("minimum_image_area_ratio must be between zero and one")
        if self.require_local_providers and self.allow_network:
            raise ValueError("local-only policy cannot allow network providers")


@dataclass(frozen=True)
class ProviderCapability:
    provider_key: str
    capability: str
    state: CapabilityState
    version: str | None = None
    local: bool = True
    requires_gpu: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentExtractionRequest:
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_reference: str
    original_file_name: str
    declared_media_type: str | None
    checksum_sha256: str
    profile: ProcessingProfile
    policy: ProcessingPolicy
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedImage:
    image_id: str
    image_hash: str
    content_type: str
    width: int
    height: int
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    bounding_box: tuple[float, float, float, float] | None = None
    content_type_classification: VisualContentType = VisualContentType.UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OcrResult:
    status: MultimodalStatus
    text: str = ""
    confidence: float | None = None
    language: str | None = None
    bounding_boxes: tuple[tuple[float, float, float, float], ...] = ()
    provider_key: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class VisualUnderstandingRequest:
    profile: ProcessingProfile
    prompt: str = "Describe the image using observable, provider-neutral facts."
    configuration: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")


@dataclass(frozen=True)
class VisualDescription:
    status: MultimodalStatus
    caption: str | None = None
    classification: VisualContentType = VisualContentType.UNKNOWN
    labels: tuple[str, ...] = ()
    confidence: float | None = None
    description: str | None = None
    observations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    provider_key: str | None = None
    provider_version: str | None = None
    profile: ProcessingProfile | None = None
    configuration_fingerprint: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")


@dataclass(frozen=True)
class DocumentExtractionResult:
    status: MultimodalStatus
    markdown: str = ""
    images: tuple[ExtractedImage, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    provider_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class DocumentExtractionProvider(Protocol):
    capability: ProviderCapability

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult: ...


class OcrProvider(Protocol):
    capability: ProviderCapability

    def recognize(self, image: ExtractedImage, payload: bytes, *, languages: Sequence[str]) -> OcrResult: ...


class ImageUnderstandingProvider(Protocol):
    capability: ProviderCapability

    def describe(
        self,
        image: ExtractedImage,
        payload: bytes,
        *,
        request: VisualUnderstandingRequest,
    ) -> VisualDescription: ...


@dataclass(frozen=True)
class VisualContentDecision:
    run_ocr: bool
    run_visual_understanding: bool
    reason: str


class VisualContentPolicy:
    def decide(
        self,
        *,
        policy: ProcessingPolicy,
        image: ExtractedImage,
        text_chars_on_page: int,
        duplicate_image: bool,
    ) -> VisualContentDecision:
        if duplicate_image:
            return VisualContentDecision(False, False, "duplicate_image")
        if image.content_type_classification in {VisualContentType.DECORATIVE, VisualContentType.LOGO}:
            return VisualContentDecision(False, False, "non_informative_image")
        if image.width <= 0 or image.height <= 0:
            return VisualContentDecision(False, False, "invalid_dimensions")

        run_ocr = policy.enable_ocr and (
            text_chars_on_page < policy.minimum_text_chars_per_page
            or image.content_type_classification
            in {
                VisualContentType.SCANNED_TEXT,
                VisualContentType.SCREENSHOT,
                VisualContentType.TABLE,
                VisualContentType.HANDWRITING,
            }
        )
        run_visual = policy.enable_visual_understanding and image.content_type_classification in {
            VisualContentType.DIAGRAM,
            VisualContentType.CHART,
            VisualContentType.PHOTOGRAPH,
            VisualContentType.SCREENSHOT,
            VisualContentType.UNKNOWN,
        }
        if run_ocr and run_visual:
            return VisualContentDecision(True, True, "ocr_and_visual_relevant")
        if run_ocr:
            return VisualContentDecision(True, False, "ocr_relevant")
        if run_visual:
            return VisualContentDecision(False, True, "visual_relevant")
        return VisualContentDecision(False, False, "policy_skipped")


DEFAULT_PROCESSING_POLICIES: dict[ProcessingProfile, ProcessingPolicy] = {
    ProcessingProfile.ECONOMY: ProcessingPolicy(
        profile=ProcessingProfile.ECONOMY,
        enable_ocr=True,
        enable_visual_understanding=False,
        allow_network=False,
        require_local_providers=False,
        minimum_text_chars_per_page=80,
        minimum_image_area_ratio=0.08,
        budget=ResourceBudget(max_ocr_pages=20, max_visual_images=0, timeout_seconds=180),
    ),
    ProcessingProfile.BALANCED: ProcessingPolicy(
        profile=ProcessingProfile.BALANCED,
        enable_ocr=True,
        enable_visual_understanding=True,
        allow_network=False,
        require_local_providers=False,
        minimum_text_chars_per_page=120,
        minimum_image_area_ratio=0.05,
        budget=ResourceBudget(max_ocr_pages=50, max_visual_images=20, timeout_seconds=300),
    ),
    ProcessingProfile.HIGH_FIDELITY: ProcessingPolicy(
        profile=ProcessingProfile.HIGH_FIDELITY,
        enable_ocr=True,
        enable_visual_understanding=True,
        allow_network=True,
        require_local_providers=False,
        minimum_text_chars_per_page=200,
        minimum_image_area_ratio=0.02,
        budget=ResourceBudget(
            max_pages=1000, max_images=300, max_ocr_pages=250, max_visual_images=100, timeout_seconds=900
        ),
    ),
    ProcessingProfile.OFFLINE_STRICT: ProcessingPolicy(
        profile=ProcessingProfile.OFFLINE_STRICT,
        enable_ocr=True,
        enable_visual_understanding=True,
        allow_network=False,
        require_local_providers=True,
        minimum_text_chars_per_page=120,
        minimum_image_area_ratio=0.05,
        budget=ResourceBudget(max_ocr_pages=40, max_visual_images=15, timeout_seconds=300),
    ),
}
