from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

_INDEXABLE_STATUSES = {"succeeded", "partial"}


def visual_artifact_metrics(artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    items = tuple((artifact or {}).get("items") or ())
    statuses: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    detected = 0
    enriched = 0
    skipped = 0
    failed = 0
    partial = 0

    for item in items:
        if not isinstance(item, Mapping):
            continue
        detected += 1
        visual = item.get("visual") if isinstance(item.get("visual"), Mapping) else {}
        status = str(visual.get("status") or "unknown").strip().lower()
        statuses[status] += 1
        provider = str(visual.get("provider_key") or "unconfigured").strip()
        providers[provider] += 1
        if status in _INDEXABLE_STATUSES:
            enriched += 1
        else:
            skipped += 1
        if status == "failed":
            failed += 1
        if status == "partial":
            partial += 1

    if failed:
        flow_status = "degraded"
    elif partial or (detected and enriched < detected):
        flow_status = "partial"
    elif detected and enriched == detected:
        flow_status = "complete"
    else:
        flow_status = "empty"

    return {
        "visual_items_detected": detected,
        "visual_items_enriched": enriched,
        "visual_items_skipped": skipped,
        "visual_items_failed": failed,
        "visual_items_partial": partial,
        "visual_provider_counts": dict(sorted(providers.items())),
        "visual_status_counts": dict(sorted(statuses.items())),
        "multimodal_flow_status": flow_status,
    }
