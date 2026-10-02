import json
from dataclasses import replace

from app.services.ingestion_artifact_registration import (
    IngestionArtifactRegistrationService,
)
from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import (
    KnowledgeArtifactStorageService,
    StoredArtifactInfo,
)
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def inspect(self, object_name):
        item = self.objects.get(object_name)
        if item is None:
            return None
        payload, content_type, metadata = item
        return StoredArtifactInfo(
            object_name=object_name,
            size_bytes=len(payload),
            sha256=metadata["sha256"],
            content_type=content_type,
            version_tag="v1",
        )

    def write(self, object_name, payload, *, content_type, metadata):
        self.objects[object_name] = (bytes(payload), content_type, dict(metadata))
        return self.inspect(object_name)


class MemoryRegistry:
    def __init__(self):
        self.records = {}
        self.save_count = 0

    def find(self, *, document_version_id, artifact_kind, object_name):
        return self.records.get((document_version_id, artifact_kind, object_name))

    def save(self, record):
        self.save_count += 1
        self.records[(record.document_version_id, record.artifact_kind, record.object_name)] = record
        return record


def build_publication():
    composition = KnowledgeNdjsonComposer().compose(
        ({"record_id": "text:1", "content": "Registry smoke.", "metadata": {"content_modality": "text"}},)
    )
    artifact = KnowledgeArtifactPublisher().build(
        composition,
        document_version_id="version-registry-1",
    )
    return KnowledgeArtifactStorageService(MemoryStorage()).publish(artifact)


def main():
    publication = build_publication()
    registry = MemoryRegistry()
    service = IngestionArtifactRegistrationService(registry)

    first = service.register(
        publication,
        document_version_id="version-registry-1",
        metadata={"pipeline": "multimodal"},
    )
    second = service.register(
        publication,
        document_version_id="version-registry-1",
        metadata={"pipeline": "ignored-on-idempotent-read"},
    )

    conflict_detected = False
    conflicting = replace(publication, sha256="0" * 64)
    try:
        service.register(conflicting, document_version_id="version-registry-1")
    except RuntimeError:
        conflict_detected = True

    unverified_rejected = False
    try:
        service.register(
            replace(publication, verified=False),
            document_version_id="version-registry-2",
        )
    except ValueError:
        unverified_rejected = True

    checks = {
        "record_saved": registry.save_count == 1,
        "idempotent_registration": first is second,
        "document_version_preserved": first.document_version_id == "version-registry-1",
        "artifact_kind_preserved": first.artifact_kind == "knowledge_ndjson",
        "object_reference_preserved": first.object_name == publication.object_name,
        "checksum_preserved": first.sha256 == publication.sha256,
        "size_preserved": first.size_bytes == publication.size_bytes,
        "content_type_preserved": first.content_type == publication.content_type,
        "publication_status_preserved": first.publication_status == "published",
        "verified_only": first.verified is True and unverified_rejected,
        "metadata_preserved": first.metadata.get("pipeline") == "multimodal",
        "timestamp_utc": first.published_at.tzinfo is not None,
        "conflict_detected": conflict_detected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "save_count": registry.save_count, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
