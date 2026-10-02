from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

VISUAL_KNOWLEDGE_SCHEMA = "visual-knowledge-record/v1"
_INDEXABLE_STATUSES = {"succeeded", "partial"}


@dataclass(frozen=True)
class VisualKnowledgeRecord:
    record_id: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VISUAL_KNOWLEDGE_SCHEMA,
            "record_id": self.record_id,
            "content": self.content,
            "metadata": dict(self.metadata),
        }


class VisualKnowledgeRecordBuilder:
    """Creates optional retrieval records from visual enrichment artifacts.

    Visual descriptions are derived knowledge. They remain independently
    traceable and must not replace or overwrite text extracted from a document.
    """

    def build(self, artifact: Mapping[str, Any] | None) -> tuple[VisualKnowledgeRecord, ...]:
        if not artifact or artifact.get("schema") != "visual-enrichment/v1":
            return ()

        records: list[VisualKnowledgeRecord] = []
        seen_hashes: set[str] = set()
        for item in artifact.get("items") or ():
            record = self._build_item(item, seen_hashes=seen_hashes)
            if record is not None:
                records.append(record)
        return tuple(records)

    def _build_item(
        self,
        item: Mapping[str, Any],
        *,
        seen_hashes: set[str],
    ) -> VisualKnowledgeRecord | None:
        image_hash = str(item.get("image_hash") or "").strip()
        if not image_hash or image_hash in seen_hashes or item.get("duplicate_of"):
            return None

        visual = item.get("visual") or {}
        status = str(visual.get("status") or "")
        if status not in _INDEXABLE_STATUSES:
            return None

        content = _compose_content(visual)
        if not content:
            return None

        seen_hashes.add(image_hash)
        source_locator = dict(item.get("source_locator") or {})
        metadata = {
            "content_modality": "visual_description",
            "derived_content": True,
            "image_id": item.get("image_id"),
            "image_hash": image_hash,
            "source_kind": item.get("source_kind"),
            "source_locator": source_locator,
            "classification": visual.get("classification"),
            "labels": list(visual.get("labels") or ()),
            "confidence": visual.get("confidence"),
            "provider_key": visual.get("provider_key"),
            "provider_version": visual.get("provider_version"),
            "processing_profile": visual.get("profile"),
            "configuration_fingerprint": visual.get("configuration_fingerprint"),
            "visual_status": status,
        }
        return VisualKnowledgeRecord(
            record_id=f"visual:{image_hash}",
            content=content,
            metadata=metadata,
        )


def _compose_content(visual: Mapping[str, Any]) -> str:
    parts: list[str] = []
    caption = _clean_text(visual.get("caption"))
    description = _clean_text(visual.get("description"))
    observations = [_clean_text(value) for value in visual.get("observations") or ()]
    observations = [value for value in observations if value]

    if caption:
        parts.append(caption)
    if description and description != caption:
        parts.append(description)
    parts.extend(value for value in observations if value not in parts)
    if not parts:
        return ""
    return "Visual content: " + " ".join(parts)


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def serialize_visual_knowledge_ndjson(records: Iterable[VisualKnowledgeRecord]) -> str:
    return "\n".join(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) for record in records)
