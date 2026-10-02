import json

from app.services.ingestion_artifact_registration import IngestionArtifactRegistrationService
from app.services.knowledge_artifact_publication_flow import (
    ArtifactRegistrationAfterPublicationError,
    KnowledgeArtifactPublicationFlow,
)
from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import KnowledgeArtifactStorageService, StoredArtifactInfo
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.removed = []

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

    def remove(self, object_name):
        self.removed.append(object_name)
        self.objects.pop(object_name, None)


class FailingRegistry:
    def find(self, **kwargs):
        return None

    def save(self, record):
        raise RuntimeError("database write failed")


def artifact():
    composition = KnowledgeNdjsonComposer().compose(
        ({"record_id": "text:1", "content": "Compensation smoke.", "metadata": {"content_modality": "text"}},)
    )
    return KnowledgeArtifactPublisher().build(
        composition,
        document_version_id="version-compensation-1",
    )


def main():
    first_storage = MemoryStorage()
    first_flow = KnowledgeArtifactPublicationFlow(
        KnowledgeArtifactStorageService(first_storage),
        IngestionArtifactRegistrationService(FailingRegistry()),
    )
    created_compensated = False
    first_error_wrapped = False
    try:
        first_flow.execute(artifact(), document_version_id="version-compensation-1")
    except ArtifactRegistrationAfterPublicationError as exc:
        created_compensated = exc.compensated
        first_error_wrapped = isinstance(exc.__cause__, RuntimeError)

    second_storage = MemoryStorage()
    existing = artifact()
    second_storage.write(
        existing.object_name,
        existing.payload,
        content_type=existing.content_type,
        metadata={"sha256": existing.manifest["sha256"]},
    )
    second_flow = KnowledgeArtifactPublicationFlow(
        KnowledgeArtifactStorageService(second_storage),
        IngestionArtifactRegistrationService(FailingRegistry()),
    )
    idempotent_not_removed = False
    try:
        second_flow.execute(existing, document_version_id="version-compensation-1")
    except ArtifactRegistrationAfterPublicationError as exc:
        idempotent_not_removed = not exc.compensated

    checks = {
        "created_object_compensated": created_compensated,
        "created_object_removed": len(first_storage.removed) == 1 and not first_storage.objects,
        "original_error_preserved": first_error_wrapped,
        "idempotent_object_not_compensated": idempotent_not_removed,
        "idempotent_object_preserved": existing.object_name in second_storage.objects,
        "idempotent_remove_not_called": second_storage.removed == [],
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
