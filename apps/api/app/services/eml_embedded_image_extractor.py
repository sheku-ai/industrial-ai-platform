from __future__ import annotations

from email import policy
from email.parser import BytesParser

from app.services.embedded_image_builder import EmbeddedImageBuilder
from app.services.embedded_image_extraction import EmbeddedImageExtractionResult


class EmlEmbeddedImageExtractor:
    def __init__(self, *, min_width: int = 32, min_height: int = 32, max_images: int = 500) -> None:
        self.min_width = min_width
        self.min_height = min_height
        self.max_images = max_images

    def extract(self, payload: bytes) -> EmbeddedImageExtractionResult:
        message = BytesParser(policy=policy.default).parsebytes(payload)
        builder = EmbeddedImageBuilder(min_width=self.min_width, min_height=self.min_height)
        occurrences = []
        skipped = 0
        message_id = message.get("Message-ID")

        for part_index, part in enumerate(message.walk()):
            if len(occurrences) >= self.max_images:
                skipped += 1
                continue
            if part.get_content_maintype() != "image":
                continue
            image_payload = part.get_payload(decode=True) or b""
            if not image_payload:
                skipped += 1
                continue
            disposition = part.get_content_disposition() or "inline"
            locator = {
                "message_id": message_id,
                "part_index": part_index,
                "content_id": part.get("Content-ID"),
                "filename": part.get_filename(),
                "disposition": disposition,
            }
            occurrence = builder.build(
                image_payload,
                content_type=part.get_content_type(),
                source_kind="eml",
                source_locator=locator,
                metadata={"source": "eml_embedded_image"},
            )
            if occurrence is None:
                skipped += 1
            else:
                occurrences.append(occurrence)

        duplicates = sum(1 for item in occurrences if item.duplicate_of is not None)
        return EmbeddedImageExtractionResult(
            occurrences=tuple(occurrences),
            unique_image_count=builder.unique_count,
            duplicate_count=duplicates,
            skipped_count=skipped,
        )
