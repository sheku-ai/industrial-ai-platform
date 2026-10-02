from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.multimodal_contracts import MultimodalStatus
from app.services.ocr_execution_service import FileOcrResultCache, OcrExecutionService
from app.services.ocr_image_preprocessor import OcrImagePreprocessor
from app.services.pdf_page_renderer import PdfPageRenderer
from app.services.tesseract_ocr_provider import TesseractOcrProvider


@dataclass(frozen=True)
class PdfOcrPageResult:
    text: str
    confidence: float | None
    language: str | None
    bounding_box_count: int
    rotation_degrees: int
    cache_hit: bool
    error_code: str | None = None


class PdfOcrEnrichmentService:
    def __init__(self, *, cache_root: str = "/app/runtime/ocr-cache") -> None:
        self.cache_root = cache_root

    def recognize_page(self, pdf_path: str, page_index: int, settings) -> PdfOcrPageResult:
        max_pages = max(int(settings.get("max_ocr_pages", 50)), 1)
        renderer = PdfPageRenderer(
            dpi=int(settings.get("ocr_dpi", 200)),
            max_pages=max_pages,
        )
        rendered = renderer.render(
            Path(pdf_path).read_bytes(),
            page_start=page_index,
            page_end_exclusive=page_index + 1,
        )[0]
        preprocessed = OcrImagePreprocessor().preprocess(
            rendered.payload,
            auto_orient=bool(settings.get("ocr_auto_orient", True)),
            grayscale=bool(settings.get("ocr_grayscale", True)),
            contrast_factor=float(settings.get("ocr_contrast_factor", 1.5)),
            threshold=_threshold(settings.get("ocr_threshold")),
        )
        provider = TesseractOcrProvider(
            enabled=True,
            timeout_seconds=int(settings.get("ocr_timeout_seconds", 30)),
        )
        service = OcrExecutionService(
            provider,
            cache=FileOcrResultCache(self.cache_root),
        )
        result = service.recognize_page(
            rendered.image,
            preprocessed.payload,
            languages=_languages(settings.get("ocr_languages")),
            preprocessing_fingerprint=(
                f"dpi={rendered.dpi};rotation={preprocessed.rotation_degrees};"
                f"gray={preprocessed.grayscale};contrast={preprocessed.contrast_factor};"
                f"threshold={preprocessed.threshold}"
            ),
        )
        return PdfOcrPageResult(
            text=result.text.strip() if result.status == MultimodalStatus.SUCCEEDED else "",
            confidence=result.confidence,
            language=result.language,
            bounding_box_count=len(result.bounding_boxes),
            rotation_degrees=preprocessed.rotation_degrees,
            cache_hit=result.metrics.get("cache_hit") is True,
            error_code=result.error_code,
        )


def _languages(value) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = value.replace(",", "+").split("+")
    elif isinstance(value, list | tuple):
        parts = value
    else:
        parts = ("eng",)
    values = tuple(str(part).strip() for part in parts if str(part).strip())
    return values or ("eng",)


def _threshold(value) -> int | None:
    if value is None:
        return None
    threshold = int(value)
    if not 0 <= threshold <= 255:
        raise ValueError("ocr_threshold must be between zero and 255")
    return threshold
