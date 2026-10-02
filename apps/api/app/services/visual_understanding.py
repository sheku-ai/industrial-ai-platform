from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from app.services.embedded_image_extraction import EmbeddedImageOccurrence
from app.services.multimodal_contracts import (
    CapabilityState,
    ImageUnderstandingProvider,
    MultimodalStatus,
    ProcessingPolicy,
    ProcessingProfile,
    ProviderCapability,
    VisualContentPolicy,
    VisualContentType,
    VisualDescription,
    VisualUnderstandingRequest,
)


class DeterministicLocalVisualProvider:
    """Offline provider that reports stable observable image properties only."""

    capability = ProviderCapability(
        provider_key="deterministic-local-vision",
        capability="image_understanding",
        state=CapabilityState.AVAILABLE,
        version="1.0",
        local=True,
        requires_gpu=False,
        details={"mode": "observable_features_only"},
    )

    def describe(
        self,
        image,
        payload: bytes,
        *,
        request: VisualUnderstandingRequest,
    ) -> VisualDescription:
        started = time.perf_counter()
        with Image.open(io.BytesIO(payload)) as source:
            rgb = source.convert("RGB")
            grayscale = rgb.convert("L")
            stats = ImageStat.Stat(grayscale)
            mean_luminance = float(stats.mean[0])
            contrast = float(stats.stddev[0])
            width, height = rgb.size

        classification = _classify_observable(
            image.content_type_classification,
            width,
            height,
            contrast,
        )
        orientation = "landscape" if width > height else "portrait" if height > width else "square"
        confidence = 0.55 if classification == VisualContentType.UNKNOWN else 0.72
        return VisualDescription(
            status=MultimodalStatus.SUCCEEDED,
            caption=f"{classification.value.replace('_', ' ').capitalize()} image ({width}x{height})",
            classification=classification,
            labels=(classification.value, orientation),
            confidence=confidence,
            description=(
                f"{orientation.capitalize()} image with dimensions {width}x{height}; "
                f"mean luminance {mean_luminance:.1f} and contrast {contrast:.1f}."
            ),
            observations=(
                f"orientation:{orientation}",
                f"mean_luminance:{mean_luminance:.1f}",
                f"contrast:{contrast:.1f}",
            ),
            warnings=("deterministic_provider_no_semantic_model",),
            provider_key=self.capability.provider_key,
            provider_version=self.capability.version,
            profile=request.profile,
            configuration_fingerprint=configuration_fingerprint(
                request.prompt,
                request.configuration,
                request.profile.value,
            ),
            metrics={
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "width": width,
                "height": height,
                "payload_bytes": len(payload),
            },
        )


def _classify_observable(
    existing: VisualContentType,
    width: int,
    height: int,
    contrast: float,
) -> VisualContentType:
    if existing != VisualContentType.UNKNOWN:
        return existing
    area = width * height
    aspect = max(width, height) / max(min(width, height), 1)
    if area < 10_000 or aspect > 8:
        return VisualContentType.DECORATIVE
    if contrast < 8:
        return VisualContentType.UNKNOWN
    return VisualContentType.DIAGRAM


def configuration_fingerprint(
    prompt: str,
    configuration: Mapping[str, Any],
    profile: str,
) -> str:
    payload = json.dumps(
        {"prompt": prompt, "configuration": dict(configuration), "profile": profile},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def visual_cache_key(
    image_hash: str,
    provider: ProviderCapability,
    request: VisualUnderstandingRequest,
) -> str:
    material = "|".join(
        (
            image_hash,
            provider.provider_key,
            provider.version or "unknown",
            configuration_fingerprint(
                request.prompt,
                request.configuration,
                request.profile.value,
            ),
            request.profile.value,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class VisualUnderstandingCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def get(self, key: str) -> VisualDescription | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["status"] = MultimodalStatus(data["status"])
            data["classification"] = VisualContentType(data["classification"])
            data["profile"] = data.get("profile") and ProcessingProfile(data["profile"])
            data["labels"] = tuple(data.get("labels") or ())
            data["observations"] = tuple(data.get("observations") or ())
            data["warnings"] = tuple(data.get("warnings") or ())
            return VisualDescription(**data)
        except Exception:
            return None

    def put(self, key: str, result: VisualDescription) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(result)
        data["status"] = result.status.value
        data["classification"] = result.classification.value
        data["profile"] = result.profile.value if result.profile else None
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(encoded)
            temporary = Path(handle.name)
        os.replace(temporary, path)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"


class VisualUnderstandingService:
    def __init__(
        self,
        provider: ImageUnderstandingProvider,
        *,
        cache: VisualUnderstandingCache | None = None,
        content_policy: VisualContentPolicy | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.content_policy = content_policy or VisualContentPolicy()
        self._processed_hashes: set[str] = set()
        self._processed_count = 0

    def capability(self, *, enabled: bool = True) -> ProviderCapability:
        capability = self.provider.capability
        if enabled:
            return capability
        return ProviderCapability(
            provider_key=capability.provider_key,
            capability=capability.capability,
            state=CapabilityState.DISABLED,
            version=capability.version,
            local=capability.local,
            requires_gpu=capability.requires_gpu,
            details=capability.details,
        )

    def enrich(
        self,
        occurrence: EmbeddedImageOccurrence,
        *,
        policy: ProcessingPolicy,
        request: VisualUnderstandingRequest,
        text_chars_on_page: int = 0,
    ) -> VisualDescription:
        capability = self.capability(enabled=policy.enable_visual_understanding)
        if capability.state != CapabilityState.AVAILABLE:
            return _skipped_or_degraded(capability, request)
        if policy.require_local_providers and not capability.local:
            return _degraded(capability, request, "non_local_provider_rejected")
        if occurrence.duplicate_of or occurrence.image.image_hash in self._processed_hashes:
            return _skipped(capability, request, "duplicate_image")
        if self._processed_count >= policy.budget.max_visual_images:
            return _skipped(capability, request, "visual_image_budget_exhausted")

        decision = self.content_policy.decide(
            policy=policy,
            image=occurrence.image,
            text_chars_on_page=text_chars_on_page,
            duplicate_image=False,
        )
        if not decision.run_visual_understanding:
            return _skipped(capability, request, decision.reason)

        key = visual_cache_key(occurrence.image.image_hash, capability, request)
        if self.cache:
            cached = self.cache.get(key)
            if cached is not None:
                return _with_cache_metric(cached, True)

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self.provider.describe,
            occurrence.image,
            occurrence.payload,
            request=request,
        )
        try:
            result = future.result(timeout=request.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return _degraded(capability, request, "visual_provider_timeout")
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            return VisualDescription(
                status=MultimodalStatus.PARTIAL,
                classification=occurrence.image.content_type_classification,
                warnings=("visual_enrichment_failed",),
                provider_key=capability.provider_key,
                provider_version=capability.version,
                profile=request.profile,
                configuration_fingerprint=configuration_fingerprint(
                    request.prompt,
                    request.configuration,
                    request.profile.value,
                ),
                metrics={"cache_hit": False},
                error_code="visual_provider_error",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        else:
            executor.shutdown(wait=True)

        self._processed_hashes.add(occurrence.image.image_hash)
        self._processed_count += 1
        result = _with_cache_metric(result, False)
        if self.cache and result.status == MultimodalStatus.SUCCEEDED:
            self.cache.put(key, result)
        return result


def _with_cache_metric(result: VisualDescription, cache_hit: bool) -> VisualDescription:
    return VisualDescription(
        **{
            **asdict(result),
            "metrics": {**dict(result.metrics), "cache_hit": cache_hit},
        }
    )


def _skipped_or_degraded(
    capability: ProviderCapability,
    request: VisualUnderstandingRequest,
) -> VisualDescription:
    if capability.state == CapabilityState.DISABLED:
        return _skipped(capability, request, "visual_understanding_disabled")
    return _degraded(capability, request, f"provider_{capability.state.value}")


def _skipped(
    capability: ProviderCapability,
    request: VisualUnderstandingRequest,
    reason: str,
) -> VisualDescription:
    return VisualDescription(
        status=MultimodalStatus.SKIPPED,
        warnings=(reason,),
        provider_key=capability.provider_key,
        provider_version=capability.version,
        profile=request.profile,
        configuration_fingerprint=configuration_fingerprint(
            request.prompt,
            request.configuration,
            request.profile.value,
        ),
        metrics={"cache_hit": False, "skip_reason": reason},
    )


def _degraded(
    capability: ProviderCapability,
    request: VisualUnderstandingRequest,
    reason: str,
) -> VisualDescription:
    return VisualDescription(
        status=MultimodalStatus.PARTIAL,
        warnings=(reason,),
        provider_key=capability.provider_key,
        provider_version=capability.version,
        profile=request.profile,
        configuration_fingerprint=configuration_fingerprint(
            request.prompt,
            request.configuration,
            request.profile.value,
        ),
        metrics={"cache_hit": False},
        error_code=reason,
        error_message=reason.replace("_", " "),
    )
