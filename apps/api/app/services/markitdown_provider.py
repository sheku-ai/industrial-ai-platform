from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from app.services.multimodal_contracts import (
    CapabilityState,
    DocumentExtractionRequest,
    DocumentExtractionResult,
    MultimodalStatus,
    ProviderCapability,
)


@dataclass(frozen=True)
class MarkItDownProviderSettings:
    enabled: bool = False
    timeout_seconds: int = 120
    max_source_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if self.max_source_bytes < 1:
            raise ValueError("max_source_bytes must be positive")


class MarkItDownProvider:
    provider_key = "markitdown"

    def __init__(self, settings: MarkItDownProviderSettings | None = None) -> None:
        self.settings = settings or MarkItDownProviderSettings()

    @staticmethod
    def package_available() -> bool:
        return importlib.util.find_spec("markitdown") is not None

    @property
    def capability(self) -> ProviderCapability:
        if not self.settings.enabled:
            state = CapabilityState.DISABLED
        elif not self.package_available():
            state = CapabilityState.UNAVAILABLE
        else:
            state = CapabilityState.AVAILABLE
        return ProviderCapability(
            provider_key=self.provider_key,
            capability="document_extraction",
            state=state,
            local=True,
            requires_gpu=False,
            details={
                "isolated_subprocess": True,
                "plugins_enabled": False,
                "network_allowed": False,
                "max_source_bytes": self.settings.max_source_bytes,
                "timeout_seconds": self.settings.timeout_seconds,
            },
        )

    def extract(self, request: DocumentExtractionRequest, payload: bytes) -> DocumentExtractionResult:
        capability = self.capability
        if capability.state == CapabilityState.DISABLED:
            return DocumentExtractionResult(
                status=MultimodalStatus.SKIPPED,
                provider_key=self.provider_key,
                error_code="provider_disabled",
                error_message="MarkItDown provider is disabled",
            )
        if capability.state == CapabilityState.UNAVAILABLE:
            return DocumentExtractionResult(
                status=MultimodalStatus.SKIPPED,
                provider_key=self.provider_key,
                error_code="provider_unavailable",
                error_message="MarkItDown package is not installed",
            )
        if len(payload) > min(self.settings.max_source_bytes, request.policy.budget.max_source_bytes):
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="source_too_large",
                error_message="source exceeds the configured extraction budget",
            )

        command = [
            sys.executable,
            "-m",
            "app.services.markitdown_runner",
            "--file-name",
            request.original_file_name,
        ]
        if request.declared_media_type:
            command.extend(["--media-type", request.declared_media_type])

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                check=False,
                timeout=min(self.settings.timeout_seconds, request.policy.budget.timeout_seconds),
            )
        except subprocess.TimeoutExpired:
            return DocumentExtractionResult(
                status=MultimodalStatus.RETRYABLE,
                provider_key=self.provider_key,
                error_code="provider_timeout",
                error_message="MarkItDown extraction exceeded the configured timeout",
                metrics={"duration_ms": round((time.perf_counter() - started) * 1000, 3)},
            )

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace")[:1000]
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="provider_execution_failed",
                error_message=detail or "MarkItDown extraction failed",
                metrics={"duration_ms": duration_ms, "return_code": completed.returncode},
            )

        try:
            result: dict[str, Any] = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return DocumentExtractionResult(
                status=MultimodalStatus.FAILED,
                provider_key=self.provider_key,
                error_code="invalid_provider_response",
                error_message=str(exc),
                metrics={"duration_ms": duration_ms},
            )

        markdown = str(result.get("markdown") or "").strip()
        if not markdown:
            return DocumentExtractionResult(
                status=MultimodalStatus.PARTIAL,
                provider_key=self.provider_key,
                error_code="empty_extraction",
                error_message="MarkItDown returned no text content",
                metrics={"duration_ms": duration_ms, "source_bytes": len(payload)},
            )

        return DocumentExtractionResult(
            status=MultimodalStatus.SUCCEEDED,
            markdown=markdown,
            provider_key=self.provider_key,
            metrics={
                "duration_ms": duration_ms,
                "source_bytes": len(payload),
                "markdown_chars": len(markdown),
                "plugins_enabled": False,
                "network_used": False,
                "llm_used": False,
                "ocr_used": False,
            },
        )
