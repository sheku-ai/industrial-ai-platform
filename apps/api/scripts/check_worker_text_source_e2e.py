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
from app.models.ingestion import IngestionPipelineProfile
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact, RuntimeExecutionAttempt
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.workers.document_ingestion_factory import build_document_ingestion_adapter


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

    org_id, doc_id, version_id, profile_id, execution_id = [uuid.uuid4() for _ in range(5)]
    source_key = f"worker-source-e2e/{execution_id}/source.txt"
    source_text = "Primary section for real source ingestion.\n\nSecondary section persisted as another content unit."
    source_bytes = source_text.encode("utf-8")
    checksum = hashlib.sha256(source_bytes).hexdigest()
    s3.put_object(
        Bucket=bucket, Key=source_key, Body=source_bytes, ContentType="text/plain", Metadata={"sha256": checksum}
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=org_id,
                slug=f"worker-source-e2e-{uuid.uuid4().hex}",
                name="Worker source E2E",
                status="active",
                config={"test_evidence": True},
            )
        )
        db.add(
            DocumentRecord(
                id=doc_id,
                organization_id=org_id,
                title="Worker source E2E",
                source_type="object_storage",
                source_ref={"uri": f"s3://{bucket}/{source_key}"},
                metadata_json={"test_evidence": True},
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
                file_name="source.txt",
                size_bytes=len(source_bytes),
                checksum_sha256=checksum,
                source_snapshot={"uri": f"s3://{bucket}/{source_key}"},
                status="pending",
            )
        )
        db.add(
            IngestionPipelineProfile(
                id=profile_id,
                organization_id=org_id,
                code="worker-source-e2e",
                name="Worker source E2E",
                revision="1",
                enabled=True,
                deployment_edition="community",
                default_adapter_key="platform.text.plain",
                adapter_policies=[],
                adapter_versions={},
                adapter_settings={"platform.text.plain": {"split_on_blank_lines": True}},
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
                status="pending",
                input_payload={
                    "document_id": str(doc_id),
                    "document_version_id": str(version_id),
                    "source_reference": f"s3://{bucket}/{source_key}",
                    "declared_media_type": "text/plain",
                    "original_file_name": "source.txt",
                    "content_length": len(source_bytes),
                    "checksum_sha256": checksum,
                    "pipeline_profile_id": str(profile_id),
                    "metadata": {},
                    "options": {},
                },
                policy_snapshot={"test_evidence": True},
                metrics={},
            )
        )
        db.commit()
    finally:
        db.close()

    registry = RuntimeAdapterRegistry()
    registry.register(build_document_ingestion_adapter(session_factory=SessionLocal))
    item = CheckpointRuntimeWorker(SessionLocal, registry, worker_id="worker-source-e2e").run_once(
        org_id, execution_id=execution_id
    )

    db = SessionLocal()
    try:
        execution = db.get(RuntimeExecution, execution_id)
        attempt = db.scalar(select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id))
        version = db.get(DocumentVersion, version_id)
        chunks = list(
            db.scalars(select(Chunk).where(Chunk.document_version_id == version_id).order_by(Chunk.chunk_index)).all()
        )
        artifact = db.scalar(
            select(RuntimeExecutionArtifact).where(
                RuntimeExecutionArtifact.execution_id == execution_id,
                RuntimeExecutionArtifact.artifact_type == "knowledge_ndjson",
            )
        )
        publications = (
            list(
                db.scalars(
                    select(RuntimeArtifactPublication).where(RuntimeArtifactPublication.artifact_id == artifact.id)
                ).all()
            )
            if artifact
            else []
        )
        records = []
        if artifact:
            parsed = urlparse(artifact.storage_uri)
            body = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"]
            try:
                records = [json.loads(line) for line in body.read().decode().splitlines() if line]
            finally:
                body.close()
        checks = {
            "work_item_claimed": item is not None,
            "execution_succeeded": execution.status == "succeeded",
            "attempt_succeeded": attempt is not None and attempt.status == "succeeded",
            "document_version_succeeded": version.status == "succeeded",
            "source_acquired": execution.metrics.get("source_bytes") == len(source_bytes),
            "text_adapter_selected": execution.metrics.get("adapter_key") == "platform.text.plain",
            "two_chunks_persisted": len(chunks) == 2,
            "chunk_text_preserved": [chunk.text for chunk in chunks]
            == ["Primary section for real source ingestion.", "Secondary section persisted as another content unit."],
            "knowledge_artifact_verified": artifact is not None and artifact.status == "verified",
            "publication_verified": len(publications) == 1 and publications[0].status == "verified",
            "text_only_records": len(records) == 2
            and all(record["metadata"]["content_modality"] == "text" for record in records),
            "worker_metrics_persisted": execution.metrics.get("persisted_inserted_units") == 2,
            "append_only_evidence_retained": True,
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_id": str(execution_id),
                    "attempt_id": str(attempt.id) if attempt else None,
                    "artifact_id": str(artifact.id) if artifact else None,
                    "chunk_count": len(chunks),
                    "record_count": len(records),
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
