from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def select_knowledge_records(
    records: Iterable[Mapping[str, Any]],
    *,
    modalities: set[str] | None = None,
    evidence_roles: set[str] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    selected = []
    for record in records:
        metadata = record.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        modality = str(metadata.get("content_modality") or "text")
        role = str(metadata.get("evidence_role") or "authoritative")
        if modalities and modality not in modalities:
            continue
        if evidence_roles and role not in evidence_roles:
            continue
        selected.append(record)
    return tuple(selected)
