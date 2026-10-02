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
from app.services.s3_visual_record_source import S3VisualRecordSource


class RuntimeArtifactRow:
    def __init__(self, storage_uri):
        self.storage_uri = storage_uri


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class RuntimeArtifactSession:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, statement):
        return ScalarRows(self._rows)


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


def ensure_bucket(client, bucket):
    try:
        client.head_bucket(Bucket=bucket)
        return False
    except Exception:
        client.create_bucket(Bucket=bucket)
        return True


def main():
    client = build_client()
    bucket = f"{os.environ.get('OBJECT_STORAGE_BUCKET', 'industrial-ai-smoke')}-multimodal-e2e".lower()
    bucket_created = ensure_bucket(client, bucket)
    run_id = str(uuid.uuid4())

    visual_key = f"runtime/{run_id}/visual-enrichment.json"
    visual_payload = {
        "schema": "visual-enrichment/v1",
        "status": "succeeded",
        "items": [
            {
                "image_id": "image-1",
                "image_hash": "a" * 64,
                "source_kind": "embedded_image",
                "source_locator": {"page": 2, "index": 1},
                "duplicate_of": None,
                "visual": {
                    "status": "succeeded",
                    "classification": "diagram",
                    "caption": "Industrial process diagram",
                    "description": "A generic process diagram with connected components.",
                    "labels": ["diagram", "process"],
                    "observations": ["Multiple connected nodes are visible."],
                    "confidence": 0.92,
                    "provider_key": "local-test-provider",
                    "provider_version": "1.0",
                    "profile": "balanced",
                    "configuration_fingerprint": "cfg-e2e",
                },
            }
        ],
    }
    client.put_object(
        Bucket=bucket,
        Key=visual_key,
        Body=json.dumps(visual_payload).encode("utf-8"),
        ContentType="application/json",
    )

    visual_records = S3VisualRecordSource(client).load(
        RuntimeArtifactSession([RuntimeArtifactRow(f"s3://{bucket}/{visual_key}")]),
        organization_id="organization-e2e",
        execution_id="execution-e2e",
    )
    text_records = (
        {
            "schema": "text-knowledge-record/v1",
            "record_id": "text:1",
            "content": "Primary textual knowledge remains authoritative.",
            "metadata": {"content_modality": "text"},
        },
    )
    composition = KnowledgeNdjsonComposer().compose(
        text_records,
        visual_records=visual_records,
    )
    artifact = KnowledgeArtifactPublisher().build(
        composition,
        document_version_id=f"multimodal-e2e-{run_id}",
        processing_revision_id=f"revision-{run_id}",
        extra_metadata={"test": "real-minio-multimodal-e2e"},
    )
    storage = KnowledgeArtifactStorageService(S3ArtifactStorageAdapter(client, bucket_name=bucket))
    first = storage.publish(artifact)
    second = storage.publish(artifact)
    response = client.get_object(Bucket=bucket, Key=artifact.object_name)
    body = response["Body"]
    try:
        downloaded = body.read().decode("utf-8")
    finally:
        body.close()
    records = [json.loads(line) for line in downloaded.splitlines() if line.strip()]

    checks = {
        "visual_artifact_persisted": client.head_object(Bucket=bucket, Key=visual_key) is not None,
        "visual_record_loaded": len(visual_records) == 1,
        "mixed_record_count": len(records) == 2,
        "text_first": records[0]["record_id"] == "text:1",
        "visual_appended": records[1]["record_id"] == f"visual:{'a' * 64}",
        "modalities_separated": (
            records[0]["metadata"]["content_modality"] == "text"
            and records[1]["metadata"]["content_modality"] == "visual_description"
        ),
        "derived_flag_preserved": records[1]["metadata"]["derived_content"] is True,
        "provider_traceability": records[1]["metadata"]["provider_key"] == "local-test-provider",
        "first_publish_succeeded": first.status == "published" and first.verified,
        "second_publish_idempotent": second.status == "already_published" and second.idempotent,
        "payload_roundtrip": downloaded == artifact.payload.decode("utf-8"),
        "revision_path_scoped": "/revisions/" in artifact.object_name,
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "bucket": bucket,
                "bucket_created": bucket_created,
                "object_name": artifact.object_name,
                "record_count": len(records),
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
