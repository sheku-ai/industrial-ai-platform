import io
import json

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.multimodal_contracts import VisualContentType
from app.services.pdf_embedded_image_extractor import PdfEmbeddedImageExtractor


def make_pdf() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 300, 160), outline="black", width=5)
    draw.line((40, 140, 160, 60, 280, 120), fill="black", width=5)
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    payload.seek(0)

    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)
    pdf.drawImage(ImageReader(payload), 60, 400, width=320, height=180)
    pdf.showPage()
    payload.seek(0)
    pdf.drawImage(ImageReader(payload), 80, 350, width=320, height=180)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def main():
    result = PdfEmbeddedImageExtractor(min_width=32, min_height=32, max_images=10).extract(make_pdf())
    first, second = result.occurrences
    checks = {
        "two_occurrences": len(result.occurrences) == 2,
        "one_unique_image": result.unique_image_count == 1,
        "one_duplicate": result.duplicate_count == 1,
        "same_hash": first.image.image_hash == second.image.image_hash,
        "duplicate_linked": second.duplicate_of == first.image.image_id,
        "page_provenance": first.image.page == 1 and second.image.page == 2,
        "locator_provenance": first.source_locator.get("page_number") == 1
        and second.source_locator.get("page_number") == 2,
        "dimensions_preserved": first.image.width == 320 and first.image.height == 180,
        "relevant_classification": first.image.content_type_classification == VisualContentType.UNKNOWN,
        "payload_preserved": len(first.payload) > 0,
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "unique_image_count": result.unique_image_count,
                "duplicate_count": result.duplicate_count,
                "skipped_count": result.skipped_count,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
