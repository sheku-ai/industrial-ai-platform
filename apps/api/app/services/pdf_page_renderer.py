from __future__ import annotations

import hashlib
from dataclasses import dataclass

import fitz

from app.services.multimodal_contracts import ExtractedImage, VisualContentType


@dataclass(frozen=True)
class RenderedPdfPage:
    page_number: int
    image: ExtractedImage
    payload: bytes
    dpi: int


class PdfPageRenderError(RuntimeError):
    pass


class PdfPageRenderer:
    def __init__(self, *, dpi: int = 200, max_pages: int = 50, max_pixels_per_page: int = 40_000_000) -> None:
        if not 72 <= dpi <= 600:
            raise ValueError("dpi must be between 72 and 600")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if max_pixels_per_page <= 0:
            raise ValueError("max_pixels_per_page must be positive")
        self.dpi = dpi
        self.max_pages = max_pages
        self.max_pixels_per_page = max_pixels_per_page

    def render(
        self, payload: bytes, *, page_start: int = 0, page_end_exclusive: int | None = None
    ) -> tuple[RenderedPdfPage, ...]:
        if not payload:
            raise PdfPageRenderError("PDF payload is empty")
        if page_start < 0:
            raise ValueError("page_start cannot be negative")

        try:
            document = fitz.open(stream=payload, filetype="pdf")
        except Exception as exc:
            raise PdfPageRenderError("PDF could not be opened") from exc

        try:
            page_count = document.page_count
            end = page_count if page_end_exclusive is None else page_end_exclusive
            if end < page_start:
                raise ValueError("page_end_exclusive cannot be lower than page_start")
            if end > page_count:
                raise ValueError("page range exceeds PDF page count")
            if end - page_start > self.max_pages:
                raise PdfPageRenderError("requested page range exceeds configured limit")

            scale = self.dpi / 72.0
            matrix = fitz.Matrix(scale, scale)
            rendered: list[RenderedPdfPage] = []
            for index in range(page_start, end):
                page = document.load_page(index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
                pixels = pixmap.width * pixmap.height
                if pixels > self.max_pixels_per_page:
                    raise PdfPageRenderError("rendered page exceeds configured pixel limit")
                image_payload = pixmap.tobytes("png")
                digest = hashlib.sha256(image_payload).hexdigest()
                image = ExtractedImage(
                    image_id=f"pdf-page-{index + 1}-{digest[:16]}",
                    image_hash=digest,
                    content_type="image/png",
                    width=pixmap.width,
                    height=pixmap.height,
                    page=index + 1,
                    content_type_classification=VisualContentType.SCANNED_TEXT,
                    metadata={
                        "source": "pdf_page_render",
                        "page_index": index,
                        "dpi": self.dpi,
                    },
                )
                rendered.append(
                    RenderedPdfPage(page_number=index + 1, image=image, payload=image_payload, dpi=self.dpi)
                )
            return tuple(rendered)
        finally:
            document.close()
