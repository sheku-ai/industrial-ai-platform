import json

from app.services.visual_knowledge_records import (
    VISUAL_KNOWLEDGE_SCHEMA,
    VisualKnowledgeRecordBuilder,
    serialize_visual_knowledge_ndjson,
)


def main():
    artifact = {
        "schema": "visual-enrichment/v1",
        "status": "partial",
        "items": [
            {
                "image_id": "img-1",
                "image_hash": "hash-1",
                "source_kind": "pptx",
                "source_locator": {"slide_number": 3},
                "duplicate_of": None,
                "visual": {
                    "status": "succeeded",
                    "caption": "Process flow diagram",
                    "description": "A sequence of connected stages.",
                    "observations": ["Three rectangular nodes", "Left-to-right arrows"],
                    "classification": "diagram",
                    "labels": ["diagram", "flow"],
                    "confidence": 0.88,
                    "provider_key": "deterministic-local-vision",
                    "provider_version": "1.0",
                    "profile": "balanced",
                    "configuration_fingerprint": "cfg-1",
                },
            },
            {
                "image_id": "img-2",
                "image_hash": "hash-1",
                "source_kind": "docx",
                "source_locator": {"section_index": 2},
                "duplicate_of": "img-1",
                "visual": {
                    "status": "skipped",
                    "caption": None,
                    "classification": "diagram",
                    "labels": [],
                },
            },
            {
                "image_id": "img-3",
                "image_hash": "hash-3",
                "source_kind": "pdf",
                "source_locator": {"page_number": 7},
                "duplicate_of": None,
                "visual": {
                    "status": "partial",
                    "caption": "Equipment layout",
                    "description": None,
                    "observations": [],
                    "classification": "diagram",
                    "labels": ["layout"],
                    "confidence": 0.61,
                    "provider_key": "local-provider",
                    "provider_version": "2",
                    "profile": "balanced",
                    "configuration_fingerprint": "cfg-2",
                    "error_code": "partial_observation",
                },
            },
            {
                "image_id": "img-4",
                "image_hash": "hash-4",
                "source_kind": "xlsx",
                "source_locator": {"sheet": "Overview"},
                "duplicate_of": None,
                "visual": {
                    "status": "failed",
                    "caption": "must not be indexed",
                    "classification": "unknown",
                    "labels": [],
                },
            },
        ],
    }

    builder = VisualKnowledgeRecordBuilder()
    records = builder.build(artifact)
    ndjson = serialize_visual_knowledge_ndjson(records)
    lines = [json.loads(line) for line in ndjson.splitlines() if line.strip()]

    checks = {
        "only_indexable_unique_records": len(records) == 2,
        "duplicate_excluded": all(record.record_id != "visual:hash-1" for record in records[1:]),
        "failed_excluded": all(record.record_id != "visual:hash-4" for record in records),
        "content_is_derived": all(record.metadata.get("derived_content") is True for record in records),
        "modality_separated": all(
            record.metadata.get("content_modality") == "visual_description" for record in records
        ),
        "provenance_preserved": (
            records[0].metadata.get("source_locator", {}).get("slide_number") == 3
            and records[1].metadata.get("source_locator", {}).get("page_number") == 7
        ),
        "provider_traceability": all(record.metadata.get("provider_key") for record in records),
        "content_prefixed": all(record.content.startswith("Visual content: ") for record in records),
        "ndjson_serializable": len(lines) == 2 and all(line.get("schema") == VISUAL_KNOWLEDGE_SCHEMA for line in lines),
        "invalid_artifact_safe": builder.build({"schema": "unknown"}) == (),
        "text_not_overwritten": all("content_modality" in record.metadata for record in records),
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "record_count": len(records), **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
