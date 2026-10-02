from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from typing import Any

from PIL import Image

from app.services.embedded_image_extraction import EmbeddedImageOccurrence
from app.services.multimodal_contracts import ExtractedImage, VisualContentType


class EmbeddedImageBuilder:
    def __init__(self, *, min_width: int = 32, min_height: int = 32) -> None:
        self.min_width = min_width
        self.min_height = min_height
        self._first_by_hash: dict[str, str] = {}

    def build(
        self,
        payload: bytes,
        *,
        content_type: str,
        source_kind: str,
        source_locator: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> EmbeddedImageOccurrence | None:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.width, image.height
        if width < self.min_width or height < self.min_height:
            return None
        digest = hashlib.sha256(payload).hexdigest()
        duplicate_of = self._first_by_hash.get(digest)
        image_id = duplicate_of or f"embedded-image-{digest[:16]}"
        if duplicate_of is None:
            self._first_by_hash[digest] = image_id
        classification = _classify(width, height)
        return EmbeddedImageOccurrence(
            image=ExtractedImage(
                image_id=image_id,
                image_hash=digest,
                content_type=content_type,
                width=width,
                height=height,
                slide=source_locator.get("slide_number"),
                sheet=source_locator.get("sheet_name"),
                content_type_classification=classification,
                metadata=dict(metadata or {}),
            ),
            payload=payload,
            source_kind=source_kind,
            source_locator=dict(source_locator),
            duplicate_of=duplicate_of,
        )

    @property
    def unique_count(self) -> int:
        return len(self._first_by_hash)


def _classify(width: int, height: int) -> VisualContentType:
    area = width * height
    aspect = max(width, height) / max(min(width, height), 1)
    if area < 10_000 or aspect > 8:
        return VisualContentType.DECORATIVE
    return VisualContentType.UNKNOWN
