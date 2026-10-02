import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageFont

from app.services.multimodal_contracts import ExtractedImage, MultimodalStatus
from app.services.ocr_image_preprocessor import OcrImagePreprocessor
from app.services.tesseract_ocr_provider import TesseractOcrProvider


class KnownOrientationPreprocessor(OcrImagePreprocessor):
    def detect_orientation(self, payload: bytes) -> int:
        return 90


def main():
    source = Image.new("RGB", (1200, 300), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    ImageDraw.Draw(source).text((50, 100), "ORIENTATION OCR 257", fill=(75, 75, 75), font=font)
    rotated = source.rotate(-90, expand=True, fillcolor="white")
    buffer = io.BytesIO()
    rotated.save(buffer, format="PNG")

    processed = KnownOrientationPreprocessor().preprocess(
        buffer.getvalue(),
        auto_orient=True,
        grayscale=True,
        contrast_factor=2.0,
        threshold=180,
    )
    image = ExtractedImage(
        image_id="preprocess-smoke",
        image_hash=hashlib.sha256(processed.payload).hexdigest(),
        content_type="image/png",
        width=processed.width,
        height=processed.height,
    )
    result = TesseractOcrProvider(enabled=True, timeout_seconds=30).recognize(
        image, processed.payload, languages=("eng",)
    )
    text = result.text.upper()
    checks = {
        "rotation_applied": processed.rotation_degrees == 90,
        "dimensions_corrected": processed.width > processed.height,
        "grayscale_applied": processed.grayscale,
        "contrast_applied": processed.contrast_factor == 2.0,
        "threshold_applied": processed.threshold == 180,
        "png_generated": processed.payload.startswith(b"\x89PNG"),
        "ocr_succeeded": result.status == MultimodalStatus.SUCCEEDED,
        "sentinel_found": "ORIENTATION" in text and "OCR" in text and "257" in text,
        "confidence_present": result.confidence is not None and result.confidence > 0,
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "recognized_text": result.text,
                "confidence": result.confidence,
                "output_width": processed.width,
                "output_height": processed.height,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
