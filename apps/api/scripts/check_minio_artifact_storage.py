import json
from types import SimpleNamespace

from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import KnowledgeArtifactStorageService
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.minio_artifact_storage import MinioArtifactStorageAdapter


class NotFoundError(Exception):
    code = "NoSuchKey"


class FakeMinioClient:
    def __init__(self):
        self.objects = {}
        self.put_calls = 0

    def stat_object(self, bucket, object_name):
        item = self.objects.get((bucket, object_name))
        if item is None:
            raise NotFoundError()
        payload, content_type, metadata = item
        return SimpleNamespace(
            size=len(payload),
            metadata={
                "content-type": content_type,
                **{f"x-amz-meta-{key}": value for key, value in metadata.items()},
            },
            etag="etag-1",
            version_id=None,
        )

    def put_object(
        self,
        bucket,
        object_name,
        data,
        length,
        *,
        content_type,
        metadata,
    ):
        payload = data.read()
        assert len(payload) == length
        self.put_calls += 1
        self.objects[(bucket, object_name)] = (
            payload,
            content_type,
            dict(metadata),
        )
        return SimpleNamespace(etag="etag-1", version_id=None)


def build_artifact():
    composition = KnowledgeNdjsonComposer().compose(
        (
            {
                "record_id": "text:1",
                "content": "Stored through MinIO adapter.",
                "metadata": {"content_modality": "text"},
            },
        )
    )
    return KnowledgeArtifactPublisher().build(
        composition,
        document_version_id="version-minio-1",
    )


def main():
    client = FakeMinioClient()
    adapter = MinioArtifactStorageAdapter(client, bucket_name="knowledge-artifacts")
    service = KnowledgeArtifactStorageService(adapter)
    artifact = build_artifact()

    missing_before_write = adapter.inspect(artifact.object_name) is None
    first = service.publish(artifact)
    second = service.publish(artifact)
    stored = adapter.inspect(artifact.object_name)

    invalid_bucket_rejected = False
    try:
        MinioArtifactStorageAdapter(client, bucket_name=" ")
    except ValueError:
        invalid_bucket_rejected = True

    checks = {
        "missing_object_safe": missing_before_write,
        "first_publish_succeeded": first.status == "published" and first.verified,
        "second_publish_idempotent": second.status == "already_published" and second.idempotent,
        "single_put_call": client.put_calls == 1,
        "stored_visible": stored is not None,
        "checksum_metadata_loaded": stored is not None and stored.sha256 == artifact.manifest["sha256"],
        "size_preserved": stored is not None and stored.size_bytes == len(artifact.payload),
        "content_type_preserved": stored is not None and stored.content_type == "application/x-ndjson",
        "version_tag_available": stored is not None and stored.version_tag == "etag-1",
        "invalid_bucket_rejected": invalid_bucket_rejected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "put_calls": client.put_calls, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
