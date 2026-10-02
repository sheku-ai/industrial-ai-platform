from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from app.services.multimodal_contracts import ExtractedImage, MultimodalStatus, OcrResult


@dataclass(frozen=True)
class OcrCachePolicy:
    enabled: bool = True
    max_entry_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if self.max_entry_bytes <= 0:
            raise ValueError("max_entry_bytes must be positive")


class FileOcrResultCache:
    def __init__(self, root: str | Path, *, policy: OcrCachePolicy | None = None) -> None:
        self.root = Path(root)
        self.policy = policy or OcrCachePolicy()
        if self.policy.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> OcrResult | None:
        if not self.policy.enabled:
            return None
        path = self._path(key)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        if len(raw) > self.policy.max_entry_bytes:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
            return OcrResult(
                status=MultimodalStatus(payload["status"]),
                text=payload.get("text", ""),
                confidence=payload.get("confidence"),
                language=payload.get("language"),
                bounding_boxes=tuple(tuple(box) for box in payload.get("bounding_boxes", [])),
                provider_key=payload.get("provider_key"),
                metrics=payload.get("metrics", {}),
                error_code=payload.get("error_code"),
                error_message=payload.get("error_message"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def put(self, key: str, result: OcrResult) -> bool:
        if not self.policy.enabled or result.status != MultimodalStatus.SUCCEEDED:
            return False
        payload = asdict(result)
        payload["status"] = result.status.value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.policy.max_entry_bytes:
            return False
        path = self._path(key)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
        return True

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"


class OcrExecutionService:
    def __init__(self, provider, *, cache: FileOcrResultCache | None = None) -> None:
        self.provider = provider
        self.cache = cache

    def recognize_page(
        self,
        image: ExtractedImage,
        payload: bytes,
        *,
        languages: Sequence[str],
        preprocessing_fingerprint: str = "none",
    ) -> OcrResult:
        key = self.cache_key(
            image=image,
            languages=languages,
            preprocessing_fingerprint=preprocessing_fingerprint,
        )
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return replace(
                    cached,
                    metrics={**dict(cached.metrics), "cache_hit": True, "cache_key": key},
                )

        result = self.provider.recognize(image, payload, languages=languages)
        stored = self.cache.put(key, result) if self.cache is not None else False
        return replace(
            result,
            metrics={
                **dict(result.metrics),
                "cache_hit": False,
                "cache_stored": stored,
                "cache_key": key,
            },
        )

    def cache_key(
        self,
        *,
        image: ExtractedImage,
        languages: Sequence[str],
        preprocessing_fingerprint: str,
    ) -> str:
        version = getattr(getattr(self.provider, "capability", None), "version", None) or "unknown"
        provider_key = getattr(self.provider, "provider_key", None) or getattr(
            getattr(self.provider, "capability", None), "provider_key", "unknown"
        )
        canonical = json.dumps(
            {
                "image_hash": image.image_hash,
                "languages": sorted(language.strip() for language in languages if language.strip()),
                "preprocessing": preprocessing_fingerprint,
                "provider_key": provider_key,
                "provider_version": version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
