from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionClass(StrEnum):
    NORMAL = "normal"
    HEAVY = "heavy"


@dataclass(frozen=True)
class InspectionResult:
    content_length: int
    detected_media_type: str
    page_count_hint: int | None
    requires_ocr_hint: bool
    execution_class: ExecutionClass
    reasons: tuple[str, ...]


class SourceInspectionService:
    def __init__(self) -> None:
        self._heavy_source_bytes = int(os.getenv("INGESTION_HEAVY_SOURCE_BYTES", "100000000"))
        self._heavy_page_count = int(os.getenv("INGESTION_HEAVY_PAGE_COUNT", "500"))

    def inspect(
        self, *, content_length: int, detected_media_type: str, options: Mapping[str, Any] | None = None
    ) -> InspectionResult:
        values = dict(options or {})
        page_count_hint = values.get("page_count_hint")
        if page_count_hint is not None and (
            not isinstance(page_count_hint, int) or isinstance(page_count_hint, bool) or page_count_hint < 0
        ):
            raise ValueError("page_count_hint must be a non-negative integer")
        requires_ocr_hint = bool(values.get("requires_ocr_hint", False))
        reasons = []
        if content_length >= self._heavy_source_bytes:
            reasons.append("source_size_threshold")
        if page_count_hint is not None and page_count_hint >= self._heavy_page_count:
            reasons.append("page_count_threshold")
        if requires_ocr_hint and detected_media_type in {"application/pdf", "image/tiff"}:
            reasons.append("ocr_expected")
        return InspectionResult(
            content_length=content_length,
            detected_media_type=detected_media_type,
            page_count_hint=page_count_hint,
            requires_ocr_hint=requires_ocr_hint,
            execution_class=ExecutionClass.HEAVY if reasons else ExecutionClass.NORMAL,
            reasons=tuple(reasons),
        )
