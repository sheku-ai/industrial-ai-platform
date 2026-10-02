from __future__ import annotations

import hashlib
import io

import fitz
from PIL import Image

from app.services.embedded_image_extraction import (
    EmbeddedImageExtractionResult,
    EmbeddedImageOccurrence,
)
from app.services.multimodal_contracts import ExtractedImage, VisualContentType


class PdfEmbeddedImageExtractor:
    def __init__(self, *, min_width: int = 32, min_height: int = 32, max_images: int = 500) -> None:
        if min_width <= 0 or min_height <= 0 or max_images <= 0:
            raise ValueError("image extraction limits must be positive")
        self.min_width = min_width
        self.min_height = min_height
        self.max_images = max_images

    def extract(self, payload: bytes) -> EmbeddedImageExtractionResult:
        if not payload:
            raise ValueError("PDF payload cannot be empty")
        document = fitz.open(stream=payload, filetype="pdf")
        occurrences = []
        first_by_hash = {}
        skipped = 0
        try:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                for image_index, image_info in enumerate(page.get_images(full=True)):
                    if len(occurrences) >= self.max_images:
                        skipped += 1
                        continue
                    xref = image_info[0]
                    extracted = document.extract_image(xref)
                    image_payload = extracted["image"]
                    width, height = _dimensions(image_payload)
                    if width < self.min_width or height < self.min_height:
                        skipped += 1
                        continue
                    digest = hashlib.sha256(image_payload).hexdigest()
                    duplicate_of = first_by_hash.get(digest)
                    image_id = duplicate_of or f"pdf-image-{digest[:16]}"
                    if duplicate_of is None:
                        first_by_hash[digest] = image_id
                    classification = _classify(width, height)
                    image = ExtractedImage(
                        image_id=image_id,
                        image_hash=digest,
                        content_type=f"image/{extracted['ext']}",
                        width=width,
                        height=height,
                        page=page_index + 1,
                        content_type_classification=classification,
                        metadata={
                            "source": "pdf_embedded_image",
                            "xref": xref,
                            "image_index": image_index,
                        },
                    )
                    occurrences.append(
                        EmbeddedImageOccurrence(
                            image=image,
                            payload=image_payload,
                            source_kind="pdf",
                            source_locator={
                                "page_number": page_index + 1,
                                "image_index": image_index,
                                "xref": xref,
                            },
                            duplicate_of=duplicate_of,
                        )
                    )
        finally:
            document.close()
        duplicates = sum(1 for item in occurrences if item.duplicate_of is not None)
        return EmbeddedImageExtractionResult(
            occurrences=tuple(occurrences),
            unique_image_count=len(first_by_hash),
            duplicate_count=duplicates,
            skipped_count=skipped,
        )


def _dimensions(payload: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(payload)) as image:
        return image.width, image.height


def _classify(width: int, height: int) -> VisualContentType:
    area = width * height
    aspect = max(width, height) / max(min(width, height), 1)
    if area < 10_000 or aspect > 8:
        return VisualContentType.DECORATIVE
    return VisualContentType.UNKNOWN
