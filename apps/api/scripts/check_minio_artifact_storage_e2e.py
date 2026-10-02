import json
import os
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import KnowledgeArtifactStorageService
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.s3_artifact_storage import S3ArtifactStorageAdapter


def build_client():
    endpoint = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL", "http://minio:9000")
    region = os.environ.get("OBJECT_STORAGE_REGION", "us-east-1")
    access_key = os.environ.get("OBJECT_STORAGE_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("OBJECT_STORAGE_SECRET_KEY", "minioadmin")
    secure = os.environ.get("OBJECT_STORAGE_SECURE", "false").lower() == "true"
    parsed = urlparse(endpoint)
    if not parsed.scheme:
        endpoint = f"{'https' if secure else 'http'}://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        verify=secure,
    )


def main():
    base_bucket = os.environ.get("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    bucket = f"{base_bucket}-visual-e2e".lower()
    client = build_client()
    adapter = S3ArtifactStorageAdapter(client, bucket_name=bucket)
    bucket_created = adapter.ensure_bucket()

    version_id = f"visual-e2e-{uuid.uuid4()}"
    composition = KnowledgeNdjsonComposer().compose(
        (
            {
                "record_id": "text:1",
                "content": "Real MinIO E2E text record.",
                "metadata": {"content_modality": "text"},
            },
        )
    )
    artifact = KnowledgeArtifactPublisher().build(
        composition,
        document_version_id=version_id,
        extra_metadata={"test": "real-minio-e2e"},
    )
    service = KnowledgeArtifactStorageService(adapter)
    first = service.publish(artifact)
    second = service.publish(artifact)
    stored = adapter.inspect(artifact.object_name)
    response = client.get_object(Bucket=bucket, Key=artifact.object_name)
    downloaded = response["Body"].read()
    response["Body"].close()

    checks = {
        "bucket_available": client.head_bucket(Bucket=bucket) is not None,
        "first_publish_succeeded": first.status == "published" and first.verified,
        "second_publish_idempotent": second.status == "already_published" and second.idempotent,
        "stored_visible": stored is not None,
        "checksum_preserved": stored is not None and stored.sha256 == artifact.manifest["sha256"],
        "size_preserved": stored is not None and stored.size_bytes == len(artifact.payload),
        "content_type_preserved": stored is not None and stored.content_type == "application/x-ndjson",
        "payload_roundtrip": downloaded == artifact.payload,
        "version_tag_available": stored is not None and bool(stored.version_tag),
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "bucket": bucket,
                "bucket_created": bucket_created,
                "object_name": artifact.object_name,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
