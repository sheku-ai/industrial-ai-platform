import contextlib
import hashlib
import json
import os
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact
from app.services.runtime_knowledge_artifact_publication import RuntimeKnowledgeArtifactPublicationService


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT_URL", "http://minio:9000"),
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def main():
    s3 = client()
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    org_id, doc_id, version_id, execution_id = [uuid.uuid4() for _ in range(4)]
    visual_key = f"runtime-e2e/{execution_id}/visual.json"
    visual = {
        "schema": "visual-enrichment/v1",
        "items": [
            {
                "image_id": "image-1",
                "image_hash": "b" * 64,
                "source_kind": "embedded_image",
                "source_locator": {"page": 1},
                "duplicate_of": None,
                "visual": {
                    "status": "succeeded",
                    "classification": "diagram",
                    "caption": "Runtime diagram",
                    "description": "Generic integration diagram.",
                    "labels": ["diagram"],
                    "observations": ["Connected nodes."],
                    "confidence": 0.9,
                    "provider_key": "runtime-e2e-provider",
                    "provider_version": "1",
                    "profile": "balanced",
                    "configuration_fingerprint": "runtime-e2e",
                },
            }
        ],
    }
    raw = json.dumps(visual, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    s3.put_object(Bucket=bucket, Key=visual_key, Body=raw, ContentType="application/json", Metadata={"sha256": sha})

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=org_id, slug=f"runtime-e2e-{uuid.uuid4().hex}", name="Runtime E2E", status="active", config={}
            )
        )
        db.add(
            DocumentRecord(
                id=doc_id,
                organization_id=org_id,
                title="Runtime E2E",
                source_type="e2e",
                source_ref={},
                metadata_json={},
                classification={},
                status="registered",
            )
        )
        db.add(
            DocumentVersion(
                id=version_id,
                organization_id=org_id,
                document_record_id=doc_id,
                version_number=1,
                content_type="text/plain",
                file_name="e2e.txt",
                size_bytes=10,
                checksum_sha256="c" * 64,
                source_snapshot={},
                status="processing",
            )
        )
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=org_id,
                execution_type="document.ingestion",
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="running",
                input_payload={},
                policy_snapshot={},
                metrics={},
            )
        )
        db.flush()
        db.add(
            Chunk(
                organization_id=org_id,
                document_record_id=doc_id,
                document_version_id=version_id,
                chunk_index=0,
                chunk_key="e2e:0",
                content_hash="d" * 64,
                text="Authoritative runtime text.",
                content_type="text",
                section_ref={},
                provenance={},
                quality={},
                metadata_json={},
                status="created",
            )
        )
        db.add(
            RuntimeExecutionArtifact(
                organization_id=org_id,
                execution_id=execution_id,
                artifact_type="visual_enrichment",
                storage_uri=f"s3://{bucket}/{visual_key}",
                media_type="application/json",
                checksum_sha256=sha,
                size_bytes=len(raw),
                metadata_={"schema": "visual-enrichment/v1"},
                status="verified",
            )
        )
        db.commit()
    finally:
        db.close()

    service = RuntimeKnowledgeArtifactPublicationService(SessionLocal, client=s3)
    artifact_id = service.publish(
        organization_id=org_id,
        execution_id=execution_id,
        attempt_id=None,
        document_version_id=version_id,
        processing_revision_id=None,
    )
    repeated_id = service.publish(
        organization_id=org_id,
        execution_id=execution_id,
        attempt_id=None,
        document_version_id=version_id,
        processing_revision_id=None,
    )

    db = SessionLocal()
    object_key = None
    try:
        artifact = db.get(RuntimeExecutionArtifact, artifact_id)
        publications = list(
            db.scalars(
                select(RuntimeArtifactPublication).where(RuntimeArtifactPublication.artifact_id == artifact_id)
            ).all()
        )
        parsed = urlparse(artifact.storage_uri)
        object_key = parsed.path.lstrip("/")
        body = s3.get_object(Bucket=parsed.netloc, Key=object_key)["Body"]
        try:
            records = [json.loads(line) for line in body.read().decode().splitlines() if line]
        finally:
            body.close()
        checks = {
            "runtime_artifact_verified": artifact.status == "verified",
            "single_publication_record": len(publications) == 1,
            "publication_verified": len(publications) == 1 and publications[0].status == "verified",
            "postgres_idempotent": repeated_id == artifact_id,
            "mixed_record_count": len(records) == 2,
            "text_first": records[0]["metadata"]["content_modality"] == "text",
            "visual_appended": records[1]["metadata"]["content_modality"] == "visual_description",
            "visual_derived": records[1]["metadata"]["derived_content"] is True,
            "provider_traceability": records[1]["metadata"]["provider_key"] == "runtime-e2e-provider",
            "metadata_counts_correct": artifact.metadata_.get("text_record_count") == 1
            and artifact.metadata_.get("visual_record_count") == 1
            and artifact.metadata_.get("visual_source_failed") is False,
            "revision_path_scoped": "/revisions/" in object_key,
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "artifact_id": str(artifact_id),
                    "object_name": object_key,
                    "record_count": len(records),
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()

    cleanup = SessionLocal()
    try:
        cleanup.execute(delete(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        cleanup.execute(delete(DocumentVersion).where(DocumentVersion.id == version_id))
        cleanup.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
        cleanup.execute(delete(Organization).where(Organization.id == org_id))
        cleanup.commit()
    finally:
        cleanup.close()
        for key in (visual_key, object_key):
            if key:
                with contextlib.suppress(Exception):
                    s3.delete_object(Bucket=bucket, Key=key)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
