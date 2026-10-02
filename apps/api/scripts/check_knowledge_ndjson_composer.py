import json

from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.visual_knowledge_records import VisualKnowledgeRecord


def main():
    text_records = (
        {
            "schema": "text-knowledge-record/v1",
            "record_id": "text:1",
            "content": "Primary extracted paragraph.",
            "metadata": {
                "content_modality": "text",
                "source_locator": {"page_number": 1},
            },
        },
        {
            "schema": "text-knowledge-record/v1",
            "record_id": "text:2",
            "content": "Secondary extracted paragraph.",
            "metadata": {
                "content_modality": "text",
                "source_locator": {"page_number": 2},
            },
        },
    )
    visual_records = (
        VisualKnowledgeRecord(
            record_id="visual:hash-1",
            content="Visual content: Process flow diagram.",
            metadata={
                "content_modality": "visual_description",
                "derived_content": True,
                "image_hash": "hash-1",
                "source_locator": {"page_number": 2},
            },
        ),
    )

    composer = KnowledgeNdjsonComposer()
    combined = composer.compose(
        text_records,
        visual_records=visual_records,
        include_visual=True,
    )
    disabled = composer.compose(
        text_records,
        visual_records=visual_records,
        include_visual=False,
    )
    parsed = [json.loads(line) for line in combined.ndjson.splitlines() if line.strip()]
    reparsed = composer.compose_from_ndjson(
        "\n".join(json.dumps(record) for record in text_records),
        visual_records=visual_records,
        include_visual=True,
    )

    invalid_rejected = False
    try:
        composer.compose_from_ndjson("[]")
    except ValueError:
        invalid_rejected = True

    checks = {
        "text_records_preserved": parsed[:2] == list(text_records),
        "text_order_preserved": [record["record_id"] for record in parsed[:2]] == ["text:1", "text:2"],
        "visual_appended": parsed[2]["record_id"] == "visual:hash-1",
        "modalities_separated": (
            parsed[0]["metadata"]["content_modality"] == "text"
            and parsed[2]["metadata"]["content_modality"] == "visual_description"
        ),
        "derived_flag_preserved": parsed[2]["metadata"]["derived_content"] is True,
        "metrics_correct": combined.metrics
        == {
            "text_records": 2,
            "visual_records_available": 1,
            "visual_records_included": 1,
            "total_records": 3,
        },
        "visual_optional": (
            len(disabled.records) == 2
            and disabled.metrics["visual_records_available"] == 1
            and disabled.metrics["visual_records_included"] == 0
        ),
        "ndjson_roundtrip": reparsed.records == combined.records,
        "invalid_ndjson_rejected": invalid_rejected,
        "text_not_overwritten": all(record["content"].startswith(("Primary", "Secondary")) for record in parsed[:2]),
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "record_count": len(parsed), **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
