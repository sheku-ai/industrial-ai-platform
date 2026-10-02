import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageFont

from app.services.multimodal_contracts import CapabilityState, ExtractedImage, MultimodalStatus
from app.services.tesseract_ocr_provider import TesseractOcrProvider

image = Image.new("RGB", (1200, 280), "white")
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
ImageDraw.Draw(image).text((50, 90), "INDUSTRIAL PLATFORM 257", fill="black", font=font)
buffer = io.BytesIO()
image.save(buffer, format="PNG")
payload = buffer.getvalue()
source = ExtractedImage(
    image_id="smoke", image_hash=hashlib.sha256(payload).hexdigest(), content_type="image/png", width=1200, height=280
)
provider = TesseractOcrProvider(enabled=True, timeout_seconds=30)
result = provider.recognize(source, payload, languages=("eng",))
text = result.text.upper()
checks = {
    "available_state": provider.capability.state == CapabilityState.AVAILABLE,
    "succeeded": result.status == MultimodalStatus.SUCCEEDED,
    "sentinel_found": "INDUSTRIAL" in text and "PLATFORM" in text and "257" in text,
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
            **checks,
        },
        indent=2,
        sort_keys=True,
    )
)
raise SystemExit(0 if passed else 1)
