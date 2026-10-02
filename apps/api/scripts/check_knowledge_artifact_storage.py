import hashlib
import json

from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import (
    KnowledgeArtifactStorageService,
    StoredArtifactInfo,
)
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer


class MemoryArtifactStorage:
    def __init__(self):
        self.objects = {}
        self.write_count = 0

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
            version_tag=str(self.write_count),
        )

    def write(self, object_name, payload, *, content_type, metadata):
        self.write_count += 1
        self.objects[object_name] = (bytes(payload), content_type, dict(metadata))
        return self.inspect(object_name)


def build_artifact(content):
    composition = KnowledgeNdjsonComposer().compose(
        ({"record_id": "text:1", "content": content, "metadata": {"content_modality": "text"}},),
    )
    return KnowledgeArtifactPublisher().build(
        composition,
        document_version_id="version-storage-1",
    )


def main():
    storage = MemoryArtifactStorage()
    service = KnowledgeArtifactStorageService(storage)
    artifact = build_artifact("Stable content")

    first = service.publish(artifact)
    second = service.publish(artifact)

    conflict_detected = False
    different = build_artifact("Different content")
    try:
        service.publish(different)
    except RuntimeError:
        conflict_detected = True

    tamper_detected = False
    tampered = type(artifact)(
        payload=artifact.payload + b"x",
        manifest=artifact.manifest,
        object_name=artifact.object_name,
        content_type=artifact.content_type,
    )
    try:
        service.publish(tampered)
    except ValueError:
        tamper_detected = True

    stored_payload, stored_type, stored_metadata = storage.objects[artifact.object_name]
    checks = {
        "first_publish_succeeded": first.status == "published" and first.verified,
        "second_publish_idempotent": second.status == "already_published" and second.idempotent,
        "single_physical_write": storage.write_count == 1,
        "checksum_preserved": stored_metadata.get("sha256") == hashlib.sha256(stored_payload).hexdigest(),
        "content_type_preserved": stored_type == "application/x-ndjson",
        "manifest_metadata_preserved": stored_metadata.get("manifest_schema") == "knowledge-artifact-manifest/v1",
        "document_version_preserved": stored_metadata.get("document_version_id") == "version-storage-1",
        "conflict_detected": conflict_detected,
        "tamper_detected": tamper_detected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "write_count": storage.write_count, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
