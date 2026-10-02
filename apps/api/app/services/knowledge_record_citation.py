from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def knowledge_record_citation(record: Mapping[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("knowledge record metadata is required")
    locator = metadata.get("source_locator")
    return {
        "record_id": str(record.get("record_id") or ""),
        "modality": str(metadata.get("content_modality") or "text"),
        "evidence_role": str(metadata.get("evidence_role") or "authoritative"),
        "citation_basis": str(metadata.get("citation_basis") or "source_text"),
        "source_locator": dict(locator) if isinstance(locator, Mapping) else {},
        "provider_key": metadata.get("provider_key"),
        "image_hash": metadata.get("image_hash"),
    }
