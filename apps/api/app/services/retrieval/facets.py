"""Metadata-driven search facets for Knowledge Runtime.

Sprint 11.3 introduces deterministic facets without hardcoded business taxonomy.

Supported field paths:
- collection_id
- content_type
- metadata.<key>
- classification.<key>

Design constraints:
- no LLM dependency;
- no vector dependency;
- no database schema change;
- no customer-specific facet names;
- fields are request-driven and UI-configurable in future iterations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DEFAULT_FACET_FIELDS: tuple[str, ...] = ("collection_id", "content_type")
MAX_FACET_FIELDS = 20
MAX_FACET_BUCKETS = 50


@dataclass(frozen=True)
class FacetBucket:
    """A single facet value count."""

    value: str
    count: int

    def as_dict(self) -> dict[str, object]:
        return {"value": self.value, "count": self.count}


@dataclass(frozen=True)
class FacetResult:
    """Facet result for one field."""

    field: str
    buckets: tuple[FacetBucket, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {"field": self.field, "buckets": [bucket.as_dict() for bucket in self.buckets]}


def normalize_facet_fields(fields: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Normalize and constrain requested facet fields."""

    requested = tuple(fields or DEFAULT_FACET_FIELDS)
    normalized: list[str] = []

    for field_name in requested:
        value = str(field_name or "").strip()
        if not value:
            continue
        if not _is_supported_field(value):
            continue
        normalized.append(value)
        if len(normalized) >= MAX_FACET_FIELDS:
            break

    return tuple(dict.fromkeys(normalized)) or DEFAULT_FACET_FIELDS


def build_facets(items: tuple, fields: tuple[str, ...] | list[str] | None = None) -> tuple[FacetResult, ...]:
    """Build deterministic facets from retrieval candidates or context items."""

    facet_fields = normalize_facet_fields(fields)
    results: list[FacetResult] = []

    for field_name in facet_fields:
        counter: Counter[str] = Counter()
        for item in items:
            values = _resolve_values(item, field_name)
            for value in values:
                counter[value] += 1

        buckets = tuple(
            FacetBucket(value=value, count=count)
            for value, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_FACET_BUCKETS]
        )
        results.append(FacetResult(field=field_name, buckets=buckets))

    return tuple(results)


def facets_as_metrics(
    items: tuple, fields: tuple[str, ...] | list[str] | None = None, *, stage: str
) -> dict[str, object]:
    facets = build_facets(items, fields)
    return {
        "facets_enabled": True,
        "facet_engine": "deterministic_metadata_v1",
        f"{stage}_facet_fields": [facet.field for facet in facets],
        f"{stage}_facet_count": len(facets),
        f"{stage}_facets": [facet.as_dict() for facet in facets],
    }


def _is_supported_field(field_name: str) -> bool:
    if field_name in {"collection_id", "content_type"}:
        return True
    if field_name.startswith("metadata.") and len(field_name) > len("metadata."):
        return True
    return bool(field_name.startswith("classification.") and len(field_name) > len("classification."))


def _resolve_values(item: Any, field_name: str) -> tuple[str, ...]:
    if field_name == "collection_id":
        value = getattr(item, "collection_id", None)
        return _coerce_values(value)

    metadata = getattr(item, "metadata", None) or {}

    if field_name == "content_type":
        return _coerce_values(metadata.get("content_type"))

    if field_name.startswith("metadata."):
        return _coerce_values(_resolve_path(metadata, field_name.removeprefix("metadata.")))

    if field_name.startswith("classification."):
        classification = getattr(item, "classification", None) or {}
        return _coerce_values(_resolve_path(classification, field_name.removeprefix("classification.")))

    return ()


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _coerce_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, list | tuple | set):
        values = [str(item).strip() for item in value if item is not None and str(item).strip()]
        return tuple(dict.fromkeys(values))

    if isinstance(value, dict):
        return ()

    text = str(value).strip()
    if not text:
        return ()

    return (text,)
