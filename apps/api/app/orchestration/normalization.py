from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.contracts.runtime_execution import ProviderExecutionResult

JsonMapping = Mapping[str, Any]


class NormalizedResponseStatus(StrEnum):
    COMPLETED = "completed"
    EMPTY = "empty"
    FAILED = "failed"


@dataclass(frozen=True)
class NormalizedProviderResponse:
    status: NormalizedResponseStatus
    text: str | None
    finish_reason: str | None
    usage: JsonMapping = field(default_factory=dict)
    latency_ms: int | None = None
    retryable: bool = False
    error_code: str | None = None
    metadata: JsonMapping = field(default_factory=dict)


class ProviderResponseNormalizer:
    def normalize(self, result: ProviderExecutionResult) -> NormalizedProviderResponse:
        status = result.status.strip().lower()
        text = result.output_text.strip() if result.output_text else None
        finish = result.finish_reason.strip().lower() if result.finish_reason else None
        usage = self._normalize_usage(result.usage)
        metadata = self._safe_metadata(result.provider_metadata)
        if status in {"completed", "success", "succeeded", "ok"}:
            if not text:
                return NormalizedProviderResponse(
                    NormalizedResponseStatus.EMPTY,
                    None,
                    finish or "empty_output",
                    usage,
                    result.latency_ms,
                    False,
                    "provider_empty_response",
                    metadata,
                )
            return NormalizedProviderResponse(
                NormalizedResponseStatus.COMPLETED,
                text,
                finish or "completed",
                usage,
                result.latency_ms,
                False,
                None,
                metadata,
            )
        code = (result.provider_error_code or "provider_execution_failed").strip().lower()
        return NormalizedProviderResponse(
            NormalizedResponseStatus.FAILED,
            None,
            finish,
            usage,
            result.latency_ms,
            bool(result.retryable),
            code,
            metadata,
        )

    def _normalize_usage(self, usage: JsonMapping) -> dict[str, int]:
        aliases = {
            "input_tokens": "input_tokens",
            "prompt_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "completion_tokens": "output_tokens",
            "total_tokens": "total_tokens",
        }
        normalized: dict[str, int] = {}
        for raw_key, raw_value in usage.items():
            key = aliases.get(str(raw_key).strip().lower())
            if key is None:
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                normalized[key] = value
        if "total_tokens" not in normalized and ("input_tokens" in normalized or "output_tokens" in normalized):
            normalized["total_tokens"] = normalized.get("input_tokens", 0) + normalized.get("output_tokens", 0)
        return normalized

    def _safe_metadata(self, metadata: JsonMapping) -> dict[str, Any]:
        forbidden = {"prompt", "rendered_prompt", "secret", "credential", "token", "api_key"}
        return {str(key): value for key, value in metadata.items() if str(key).strip().lower() not in forbidden}
