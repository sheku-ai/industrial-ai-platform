import json

from app.services.knowledge_artifact_publisher import (
    KNOWLEDGE_ARTIFACT_SCHEMA,
    KnowledgeArtifactPublisher,
)
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.visual_knowledge_records import VisualKnowledgeRecord


def main():
    text_records = (
        {
            "schema": "text-knowledge-record/v1",
            "record_id": "text:1",
            "content": "Primary extracted content.",
            "metadata": {"content_modality": "text"},
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
            },
        ),
    )

    composition = KnowledgeNdjsonComposer().compose(
        text_records,
        visual_records=visual_records,
        include_visual=True,
    )
    publisher = KnowledgeArtifactPublisher()
    artifact = publisher.build(
        composition,
        document_version_id="version-123",
        extra_metadata={"pipeline": "multimodal"},
    )
    manifest_json = publisher.manifest_json(artifact)
    manifest = json.loads(manifest_json)

    tampered = type(artifact)(
        payload=artifact.payload + b"x",
        manifest=artifact.manifest,
        object_name=artifact.object_name,
    )

    invalid_name_rejected = False
    try:
        publisher.build(
            composition,
            document_version_id="version-123",
            artifact_name="nested/knowledge.ndjson",
        )
    except ValueError:
        invalid_name_rejected = True

    checks = {
        "manifest_schema": manifest.get("schema") == KNOWLEDGE_ARTIFACT_SCHEMA,
        "object_name_scoped": artifact.object_name == "document-versions/version-123/knowledge.ndjson",
        "content_type_correct": artifact.content_type == "application/x-ndjson",
        "checksum_valid": publisher.verify(artifact),
        "tamper_detected": publisher.verify(tampered) is False,
        "record_counts_correct": (
            manifest.get("record_count") == 2
            and manifest.get("text_record_count") == 1
            and manifest.get("visual_record_count") == 1
            and manifest.get("visual_records_available") == 1
        ),
        "size_recorded": manifest.get("size_bytes") == len(artifact.payload),
        "metadata_preserved": manifest.get("metadata", {}).get("pipeline") == "multimodal",
        "manifest_serializable": json.loads(json.dumps(manifest)) == manifest,
        "invalid_name_rejected": invalid_name_rejected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "object_name": artifact.object_name, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
