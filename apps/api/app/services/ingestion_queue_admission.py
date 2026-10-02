from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionQueuePolicy:
    heavy_bytes_threshold: int = 100_000_000
    heavy_pages_threshold: int = 500
    max_consecutive_heavy: int = 1

    def __post_init__(self) -> None:
        if self.heavy_bytes_threshold <= 0:
            raise ValueError("heavy_bytes_threshold must be positive")
        if self.heavy_pages_threshold <= 0:
            raise ValueError("heavy_pages_threshold must be positive")
        if self.max_consecutive_heavy <= 0:
            raise ValueError("max_consecutive_heavy must be positive")


class IngestionQueueAdmission:
    def __init__(self, policy: IngestionQueuePolicy) -> None:
        self.policy = policy
        self._consecutive_heavy = 0

    def classify(self, payload: Mapping[str, Any]) -> str:
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        content_length = payload.get("content_length")
        page_count = options.get("page_count_hint")
        requires_ocr = options.get("requires_ocr_hint") is True
        heavy = (
            requires_ocr
            or (
                isinstance(content_length, int)
                and not isinstance(content_length, bool)
                and content_length >= self.policy.heavy_bytes_threshold
            )
            or (
                isinstance(page_count, int)
                and not isinstance(page_count, bool)
                and page_count >= self.policy.heavy_pages_threshold
            )
        )
        return "heavy" if heavy else "normal"

    def choose(self, candidates):
        normal = [candidate for candidate in candidates if self.classify(candidate.input_payload) == "normal"]
        heavy = [candidate for candidate in candidates if self.classify(candidate.input_payload) == "heavy"]
        if normal and self._consecutive_heavy >= self.policy.max_consecutive_heavy:
            self._consecutive_heavy = 0
            return normal[0], "normal"
        if normal:
            self._consecutive_heavy = 0
            return normal[0], "normal"
        if heavy:
            self._consecutive_heavy += 1
            return heavy[0], "heavy"
        return None, None
