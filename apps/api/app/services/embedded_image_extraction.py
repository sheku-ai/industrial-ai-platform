from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.multimodal_contracts import ExtractedImage


@dataclass(frozen=True)
class EmbeddedImageOccurrence:
    image: ExtractedImage
    payload: bytes
    source_kind: str
    source_locator: Mapping[str, Any] = field(default_factory=dict)
    duplicate_of: str | None = None


@dataclass(frozen=True)
class EmbeddedImageExtractionResult:
    occurrences: tuple[EmbeddedImageOccurrence, ...]
    unique_image_count: int
    duplicate_count: int
    skipped_count: int = 0


class EmbeddedImageExtractor(Protocol):
    def extract(self, payload: bytes) -> EmbeddedImageExtractionResult: ...
