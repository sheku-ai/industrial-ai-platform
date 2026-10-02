import json

from app.services.multimodal_contracts import CapabilityState, ExtractedImage, MultimodalStatus
from app.services.tesseract_ocr_provider import TesseractOcrProvider


def main():
    disabled = TesseractOcrProvider(enabled=False)
    unavailable = TesseractOcrProvider(enabled=True, executable="industrial-ai-missing-tesseract")
    image = ExtractedImage(
        image_id="smoke",
        image_hash="0" * 64,
        content_type="image/png",
        width=1,
        height=1,
    )
    disabled_result = disabled.recognize(image, b"x", languages=("eng",))
    unavailable_result = unavailable.recognize(image, b"x", languages=("eng",))
    checks = {
        "disabled_state": disabled.capability.state == CapabilityState.DISABLED,
        "disabled_result_skipped": disabled_result.status == MultimodalStatus.SKIPPED,
        "disabled_error_code": disabled_result.error_code == "ocr_provider_disabled",
        "unavailable_state": unavailable.capability.state == CapabilityState.UNAVAILABLE,
        "unavailable_result_skipped": unavailable_result.status == MultimodalStatus.SKIPPED,
        "unavailable_error_code": unavailable_result.error_code == "ocr_provider_unavailable",
        "local_provider": disabled.capability.local and unavailable.capability.local,
        "gpu_not_required": not disabled.capability.requires_gpu and not unavailable.capability.requires_gpu,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
