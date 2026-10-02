from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.services.multimodal_contracts import (
    CapabilityState,
    ExtractedImage,
    MultimodalStatus,
    OcrResult,
    ProviderCapability,
)


class TesseractOcrProvider:
    provider_key = "platform.ocr.tesseract"

    def __init__(
        self,
        *,
        enabled: bool = True,
        executable: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._enabled = enabled
        self._executable = executable or os.getenv("TESSERACT_EXECUTABLE") or "tesseract"
        self._timeout_seconds = timeout_seconds
        self.capability = self._detect_capability()

    def _detect_capability(self) -> ProviderCapability:
        if not self._enabled:
            return ProviderCapability(
                provider_key=self.provider_key,
                capability="ocr",
                state=CapabilityState.DISABLED,
                local=True,
                requires_gpu=False,
                details={"reason": "provider_disabled"},
            )
        resolved = shutil.which(self._executable)
        if resolved is None:
            return ProviderCapability(
                provider_key=self.provider_key,
                capability="ocr",
                state=CapabilityState.UNAVAILABLE,
                local=True,
                requires_gpu=False,
                details={"reason": "executable_not_found", "executable": self._executable},
            )
        version = None
        try:
            completed = subprocess.run(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=min(self._timeout_seconds, 10),
                check=False,
            )
            first_line = (completed.stdout or completed.stderr or "").splitlines()
            if first_line:
                version = first_line[0].strip()
        except (OSError, subprocess.SubprocessError):
            version = None
        return ProviderCapability(
            provider_key=self.provider_key,
            capability="ocr",
            state=CapabilityState.AVAILABLE,
            version=version,
            local=True,
            requires_gpu=False,
            details={"executable": resolved},
        )

    def recognize(self, image: ExtractedImage, payload: bytes, *, languages: Sequence[str]) -> OcrResult:
        if self.capability.state == CapabilityState.DISABLED:
            return OcrResult(
                status=MultimodalStatus.SKIPPED,
                provider_key=self.provider_key,
                error_code="ocr_provider_disabled",
                error_message="Tesseract OCR provider is disabled",
            )
        if self.capability.state != CapabilityState.AVAILABLE:
            return OcrResult(
                status=MultimodalStatus.SKIPPED,
                provider_key=self.provider_key,
                error_code="ocr_provider_unavailable",
                error_message="Tesseract executable is not available",
            )
        if not payload:
            return OcrResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="empty_image_payload",
                error_message="OCR requires a non-empty image payload",
            )

        suffix = _suffix_for_content_type(image.content_type)
        language_arg = "+".join(language.strip() for language in languages if language.strip()) or "eng"
        executable = str(self.capability.details["executable"])
        try:
            with tempfile.TemporaryDirectory(prefix="industrial-ai-ocr-") as workspace:
                source_path = Path(workspace) / f"source{suffix}"
                source_path.write_bytes(payload)
                completed = subprocess.run(
                    [executable, str(source_path), "stdout", "-l", language_arg, "tsv"],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    check=False,
                )
                if completed.returncode != 0:
                    return OcrResult(
                        status=MultimodalStatus.FAILED,
                        provider_key=self.provider_key,
                        error_code="ocr_execution_failed",
                        error_message=(completed.stderr or "Tesseract execution failed").strip()[:2000],
                        metrics={"return_code": completed.returncode},
                    )
                text, confidence, boxes = _parse_tsv(completed.stdout)
                return OcrResult(
                    status=MultimodalStatus.SUCCEEDED,
                    text=text,
                    confidence=confidence,
                    language=language_arg,
                    bounding_boxes=boxes,
                    provider_key=self.provider_key,
                    metrics={"timeout_seconds": self._timeout_seconds, "word_count": len(text.split())},
                )
        except subprocess.TimeoutExpired:
            return OcrResult(
                status=MultimodalStatus.RETRYABLE,
                provider_key=self.provider_key,
                error_code="ocr_timeout",
                error_message="Tesseract OCR exceeded the configured timeout",
                metrics={"timeout_seconds": self._timeout_seconds},
            )
        except OSError as exc:
            return OcrResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="ocr_io_error",
                error_message=str(exc),
            )


def _suffix_for_content_type(content_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
    }.get(content_type.lower(), ".img")


def _parse_tsv(value: str) -> tuple[str, float | None, tuple[tuple[float, float, float, float], ...]]:
    words: list[str] = []
    confidences: list[float] = []
    boxes: list[tuple[float, float, float, float]] = []
    lines = value.splitlines()
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) < 12:
            continue
        text = columns[11].strip()
        if not text:
            continue
        try:
            confidence = float(columns[10])
            left, top, width, height = map(float, columns[6:10])
        except ValueError:
            continue
        words.append(text)
        if confidence >= 0:
            confidences.append(confidence / 100.0)
        boxes.append((left, top, left + width, top + height))
    average = sum(confidences) / len(confidences) if confidences else None
    return " ".join(words), average, tuple(boxes)
