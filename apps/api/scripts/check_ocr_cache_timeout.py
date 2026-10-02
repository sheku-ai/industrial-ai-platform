import hashlib
import json
import tempfile
from pathlib import Path

from app.services.multimodal_contracts import (
    CapabilityState,
    ExtractedImage,
    MultimodalStatus,
    OcrResult,
    ProviderCapability,
)
from app.services.ocr_execution_service import FileOcrResultCache, OcrExecutionService
from app.services.tesseract_ocr_provider import TesseractOcrProvider


class CountingProvider:
    provider_key = "smoke.ocr.counting"

    def __init__(self):
        self.calls = 0
        self.capability = ProviderCapability(
            provider_key=self.provider_key,
            capability="ocr",
            state=CapabilityState.AVAILABLE,
            version="1",
            local=True,
            requires_gpu=False,
        )

    def recognize(self, image, payload, *, languages):
        self.calls += 1
        return OcrResult(
            status=MultimodalStatus.SUCCEEDED,
            text="CACHE OCR 257",
            confidence=0.99,
            language="+".join(languages),
            provider_key=self.provider_key,
            metrics={"provider_calls": self.calls},
        )


def main():
    payload = b"ocr-cache-smoke"
    image = ExtractedImage(
        image_id="cache-smoke",
        image_hash=hashlib.sha256(payload).hexdigest(),
        content_type="image/png",
        width=100,
        height=50,
        page=1,
    )

    with tempfile.TemporaryDirectory(prefix="industrial-ai-ocr-cache-") as workspace:
        provider = CountingProvider()
        cache = FileOcrResultCache(Path(workspace) / "cache")
        service = OcrExecutionService(provider, cache=cache)
        first = service.recognize_page(image, payload, languages=("eng",), preprocessing_fingerprint="gray-v1")
        second = service.recognize_page(image, payload, languages=("eng",), preprocessing_fingerprint="gray-v1")
        third = service.recognize_page(image, payload, languages=("eng",), preprocessing_fingerprint="binary-v1")

        executable = Path(workspace) / "slow-tesseract"
        executable.write_text(
            '#!/bin/sh\nif [ "$1" = "--version" ]; then echo slow-tesseract-1; exit 0; fi\nsleep 2\n', encoding="utf-8"
        )
        executable.chmod(0o755)
        timeout_provider = TesseractOcrProvider(enabled=True, executable=str(executable), timeout_seconds=1)
        timeout_result = timeout_provider.recognize(image, payload, languages=("eng",))

        checks = {
            "first_cache_miss": first.metrics.get("cache_hit") is False,
            "first_cache_stored": first.metrics.get("cache_stored") is True,
            "second_cache_hit": second.metrics.get("cache_hit") is True,
            "same_key_reused": first.metrics.get("cache_key") == second.metrics.get("cache_key"),
            "provider_not_reexecuted_on_hit": provider.calls == 2,
            "preprocessing_changes_key": third.metrics.get("cache_key") != first.metrics.get("cache_key"),
            "timeout_retryable": timeout_result.status == MultimodalStatus.RETRYABLE,
            "timeout_error_code": timeout_result.error_code == "ocr_timeout",
            "timeout_metric_present": timeout_result.metrics.get("timeout_seconds") == 1,
        }
        passed = all(checks.values())
        print(json.dumps({"passed": passed, "provider_calls": provider.calls, **checks}, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
