import contextlib
import hashlib
import json
import os
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact, RuntimeExecutionAttempt
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.runtime_knowledge_artifact_publication import RuntimeKnowledgeArtifactPublicationService
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeAdapterResult


class PublicationAdapter:
    execution_type = "e2e.multimodal.publication"

    def __init__(self, publisher):
        self.publisher = publisher

    def execute(self, item, heartbeat):
        heartbeat.checkpoint()
        artifact_id = self.publisher.publish(
            organization_id=item.organization_id,
            execution_id=item.execution_id,
            attempt_id=item.attempt_id,
            document_version_id=item.subject_id,
            processing_revision_id=None,
        )
        heartbeat.checkpoint()
        return RuntimeAdapterResult(metrics={"knowledge_artifact_id": str(artifact_id)})


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT_URL", "http://minio:9000"),
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def main():
    s3 = s3_client()
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    org_id, doc_id, version_id, execution_id = [uuid.uuid4() for _ in range(4)]
    visual_key = f"worker-e2e/{execution_id}/visual.json"
    visual = {
        "schema": "visual-enrichment/v1",
        "items": [
            {
                "image_id": "worker-image-1",
                "image_hash": "e" * 64,
                "source_kind": "embedded_image",
                "source_locator": {"page": 1},
                "duplicate_of": None,
                "visual": {
                    "status": "succeeded",
                    "classification": "diagram",
                    "caption": "Worker lifecycle diagram",
                    "description": "Generic worker publication validation diagram.",
                    "labels": ["diagram"],
                    "observations": ["Connected nodes."],
                    "confidence": 0.91,
                    "provider_key": "worker-e2e-provider",
                    "provider_version": "1",
                    "profile": "balanced",
                    "configuration_fingerprint": "worker-e2e",
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
                id=org_id, slug=f"worker-e2e-{uuid.uuid4().hex}", name="Worker E2E", status="active", config={}
            )
        )
        db.add(
            DocumentRecord(
                id=doc_id,
                organization_id=org_id,
                title="Worker E2E",
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
                file_name="worker-e2e.txt",
                size_bytes=10,
                checksum_sha256="f" * 64,
                source_snapshot={},
                status="processing",
            )
        )
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=org_id,
                execution_type=PublicationAdapter.execution_type,
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="pending",
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
                chunk_key="worker-e2e:0",
                content_hash="a" * 64,
                text="Worker authoritative text.",
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

    registry = RuntimeAdapterRegistry()
    registry.register(PublicationAdapter(RuntimeKnowledgeArtifactPublicationService(SessionLocal, client=s3)))
    worker = CheckpointRuntimeWorker(SessionLocal, registry, worker_id="worker-e2e")
    item = worker.run_once(org_id, execution_id=execution_id)

    db = SessionLocal()
    knowledge_key = None
    try:
        execution = db.get(RuntimeExecution, execution_id)
        attempt = db.scalar(select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id))
        artifact = db.scalar(
            select(RuntimeExecutionArtifact).where(
                RuntimeExecutionArtifact.execution_id == execution_id,
                RuntimeExecutionArtifact.artifact_type == "knowledge_ndjson",
            )
        )
        publications = list(
            db.scalars(
                select(RuntimeArtifactPublication).where(RuntimeArtifactPublication.artifact_id == artifact.id)
            ).all()
        )
        parsed = urlparse(artifact.storage_uri)
        knowledge_key = parsed.path.lstrip("/")
        body = s3.get_object(Bucket=parsed.netloc, Key=knowledge_key)["Body"]
        try:
            records = [json.loads(line) for line in body.read().decode().splitlines() if line]
        finally:
            body.close()
        checks = {
            "work_item_claimed": item is not None,
            "execution_succeeded": execution.status == "succeeded",
            "attempt_succeeded": attempt is not None and attempt.status == "succeeded",
            "attempt_linked": artifact.attempt_id == attempt.id,
            "worker_metrics_persisted": execution.metrics.get("knowledge_artifact_id") == str(artifact.id),
            "artifact_verified": artifact.status == "verified",
            "publication_verified": len(publications) == 1 and publications[0].status == "verified",
            "mixed_records": len(records) == 2,
            "text_first": records[0]["metadata"]["content_modality"] == "text",
            "visual_appended": records[1]["metadata"]["content_modality"] == "visual_description",
            "provider_traceability": records[1]["metadata"]["provider_key"] == "worker-e2e-provider",
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_id": str(execution_id),
                    "attempt_id": str(attempt.id),
                    "artifact_id": str(artifact.id),
                    "database_evidence_retained": True,
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
        for key in (visual_key, knowledge_key):
            if key:
                with contextlib.suppress(Exception):
                    s3.delete_object(Bucket=bucket, Key=key)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
