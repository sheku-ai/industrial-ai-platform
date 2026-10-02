from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from app.services.visual_understanding_batch import VisualEnrichmentBatchResult

ARTIFACT_SCHEMA = "visual-enrichment/v1"


def serialize_visual_enrichment_batch(
    batch: VisualEnrichmentBatchResult,
    *,
    extraction_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": ARTIFACT_SCHEMA,
        "status": batch.status.value,
        "metrics": dict(batch.metrics),
        "warnings": list(batch.warnings),
        "extraction_metrics": dict(extraction_metrics or {}),
        "items": [
            {
                "image_id": item.image_id,
                "image_hash": item.image_hash,
                "source_kind": item.source_kind,
                "source_locator": dict(item.source_locator),
                "duplicate_of": item.duplicate_of,
                "visual": _serialize_visual_description(item.result),
            }
            for item in batch.items
        ],
    }


def _serialize_visual_description(result) -> dict[str, Any]:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["classification"] = result.classification.value
    payload["profile"] = result.profile.value if result.profile else None
    payload["labels"] = list(result.labels)
    payload["observations"] = list(result.observations)
    payload["warnings"] = list(result.warnings)
    payload["metrics"] = dict(result.metrics)
    return payload
