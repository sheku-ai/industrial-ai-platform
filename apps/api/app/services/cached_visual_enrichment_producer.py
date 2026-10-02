from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.services.duplicate_work_cache import BoundedDuplicateWorkCache


class CachedVisualEnrichmentProducer:
    """Reuses derived visual artifacts by tenant, checksum and configuration."""

    def __init__(self, delegate, acquisition, *, cache=None) -> None:
        self._delegate = delegate
        self._acquisition = acquisition
        self._cache = cache or BoundedDuplicateWorkCache[Mapping[str, Any] | None]()

    def produce(self, item, heartbeat) -> Mapping[str, Any] | None:
        payload = item.input_payload if isinstance(item.input_payload, dict) else {}
        source_reference = payload.get("source_reference")
        if not isinstance(source_reference, str) or not source_reference.strip():
            return self._delegate.produce(item, heartbeat)

        handle = self._acquisition.open_handle(source_reference.strip())
        checksum = handle.checksum_sha256
        if not checksum:
            return self._delegate.produce(item, heartbeat)

        key = _source_cache_key(
            organization_id=getattr(item, "organization_id", None),
            checksum=checksum,
            options=payload.get("options"),
            policy_snapshot=getattr(item, "policy_snapshot", None),
            media_type=payload.get("declared_media_type") or handle.detected_media_type,
        )
        result = self._cache.get_or_compute(
            key,
            lambda: self._delegate.produce(item, heartbeat),
        )
        return result.value

    def metrics(self) -> dict[str, int]:
        return self._cache.metrics()


def _source_cache_key(
    *,
    organization_id,
    checksum: str,
    options,
    policy_snapshot,
    media_type,
) -> str:
    material = json.dumps(
        {
            "organization_id": str(organization_id or ""),
            "checksum": str(checksum).lower(),
            "options": options if isinstance(options, dict) else {},
            "policy_snapshot": policy_snapshot if isinstance(policy_snapshot, dict) else {},
            "media_type": str(media_type or "").lower(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
