from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.multimodal_fusion_contracts import fuse_knowledge_record
from app.services.visual_knowledge_records import VisualKnowledgeRecord


@dataclass(frozen=True)
class KnowledgeArtifactComposition:
    ndjson: str
    records: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, int] = field(default_factory=dict)


class KnowledgeNdjsonComposer:
    """Builds an ordered multimodal knowledge stream with governed evidence roles."""

    def compose(
        self,
        text_records: Iterable[Mapping[str, Any]],
        *,
        visual_records: Sequence[VisualKnowledgeRecord] = (),
        include_visual: bool = True,
    ) -> KnowledgeArtifactComposition:
        normalized_text = tuple(_copy_record(record) for record in text_records)
        normalized_visual = tuple(record.as_dict() for record in visual_records) if include_visual else ()
        source_records = (*normalized_text, *normalized_visual)
        records = tuple(
            fuse_knowledge_record(record, fusion_order=index) for index, record in enumerate(source_records)
        )
        ndjson = "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
        return KnowledgeArtifactComposition(
            ndjson=ndjson,
            records=records,
            metrics={
                "text_records": len(normalized_text),
                "visual_records_available": len(visual_records),
                "visual_records_included": len(normalized_visual),
                "authoritative_records": sum(1 for record in records if record["metadata"]["authoritative"] is True),
                "derived_records": sum(1 for record in records if record["metadata"]["derived_content"] is True),
                "total_records": len(records),
            },
        )

    def compose_from_ndjson(
        self,
        text_ndjson: str,
        *,
        visual_records: Sequence[VisualKnowledgeRecord] = (),
        include_visual: bool = True,
    ) -> KnowledgeArtifactComposition:
        text_records: list[Mapping[str, Any]] = []
        for line_number, raw_line in enumerate(text_ndjson.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"NDJSON line {line_number} must contain an object")
            text_records.append(value)
        return self.compose(
            text_records,
            visual_records=visual_records,
            include_visual=include_visual,
        )


def _copy_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise TypeError("knowledge records must be mappings")
    return dict(record)
