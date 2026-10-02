import io
import json

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.multimodal_contracts import MultimodalStatus
from app.services.pdf_page_renderer import PdfPageRenderer
from app.services.tesseract_ocr_provider import TesseractOcrProvider

SENTINEL = "SCANNED PDF PAGE 257"


def build_scanned_pdf() -> bytes:
    image = Image.new("RGB", (1400, 500), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 82)
    ImageDraw.Draw(image).text((70, 180), SENTINEL, fill="black", font=font)
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=letter)
    pdf.drawImage(ImageReader(image_buffer), 36, 280, width=540, height=193, preserveAspectRatio=True, mask="auto")
    pdf.showPage()
    pdf.save()
    return pdf_buffer.getvalue()


def main():
    renderer = PdfPageRenderer(dpi=200, max_pages=2, max_pixels_per_page=20_000_000)
    pages = renderer.render(build_scanned_pdf(), page_start=0, page_end_exclusive=1)
    provider = TesseractOcrProvider(enabled=True, timeout_seconds=30)
    result = provider.recognize(pages[0].image, pages[0].payload, languages=("eng",))
    normalized = result.text.upper()

    checks = {
        "one_page_rendered": len(pages) == 1,
        "page_number_preserved": pages[0].page_number == 1 and pages[0].image.page == 1,
        "png_generated": pages[0].image.content_type == "image/png" and pages[0].payload.startswith(b"\x89PNG"),
        "dimensions_present": pages[0].image.width > 0 and pages[0].image.height > 0,
        "dpi_preserved": pages[0].dpi == 200 and pages[0].image.metadata.get("dpi") == 200,
        "ocr_succeeded": result.status == MultimodalStatus.SUCCEEDED,
        "sentinel_found": "SCANNED" in normalized and "PDF" in normalized and "257" in normalized,
        "confidence_present": result.confidence is not None and result.confidence > 0,
        "bounding_boxes_present": len(result.bounding_boxes) >= 3,
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "recognized_text": result.text,
                "confidence": result.confidence,
                "bounding_box_count": len(result.bounding_boxes),
                "rendered_width": pages[0].image.width,
                "rendered_height": pages[0].image.height,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
