import contextlib
import hashlib
import io
import json
import os
import uuid
import zipfile

import boto3
from botocore.config import Config
from PIL import Image, ImageDraw

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.runtime_visual_enrichment_producer import RuntimeVisualEnrichmentProducer
from app.services.runtime_worker import RuntimeAdapterRegistry, RuntimeAdapterResult
from app.services.s3_source_acquisition import S3SourceAcquisitionService


class VisualProducerAdapter:
    execution_type = "e2e.visual.producer"

    def __init__(self, producer):
        self.producer = producer
        self.artifact = None

    def execute(self, item, heartbeat):
        self.artifact = self.producer.produce(item, heartbeat)
        visual_items = [] if self.artifact is None else list(self.artifact.get("items", []))
        return RuntimeAdapterResult(
            metrics={
                "visual_enrichment_connected": True,
                "visual_enrichment_published": False,
                "visual_enrichment_item_count": len(visual_items),
                "visual_enrichment_schema": None if self.artifact is None else self.artifact.get("schema"),
            }
        )


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT_URL", "http://minio:9000"),
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def build_docx_with_embedded_image():
    image_buffer = io.BytesIO()
    image = Image.new("RGB", (160, 96), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((12, 12, 148, 84), outline="black", width=3)
    drawing.line((30, 48, 130, 48), fill="black", width=3)
    image.save(image_buffer, format="PNG")
    image_payload = image_buffer.getvalue()

    relationship_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    Target="media/image1.png"/>
</Relationships>
"""
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/_rels/document.xml.rels", relationship_xml)
        archive.writestr("word/media/image1.png", image_payload)
    return package.getvalue()


def main():
    os.environ["VISUAL_UNDERSTANDING_ENABLED"] = "1"
    os.environ["VISUAL_UNDERSTANDING_PROVIDER"] = "deterministic-local"
    os.environ["VISUAL_UNDERSTANDING_PROFILE"] = "balanced"

    s3 = s3_client()
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    organization_id, document_id, version_id, execution_id = [uuid.uuid4() for _ in range(4)]
    source_key = f"worker-visual-producer-e2e/{execution_id}/embedded-image.docx"
    source_payload = build_docx_with_embedded_image()
    source_sha = hashlib.sha256(source_payload).hexdigest()
    s3.put_object(
        Bucket=bucket,
        Key=source_key,
        Body=source_payload,
        ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        Metadata={"sha256": source_sha},
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"worker-visual-{uuid.uuid4().hex}",
                name="Worker Visual Producer E2E",
                status="active",
                config={},
            )
        )
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Worker Visual Producer E2E",
                source_type="e2e",
                source_ref={"uri": f"s3://{bucket}/{source_key}"},
                metadata_json={},
                classification={},
                status="registered",
            )
        )
        db.add(
            DocumentVersion(
                id=version_id,
                organization_id=organization_id,
                document_record_id=document_id,
                version_number=1,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_name="embedded-image.docx",
                size_bytes=len(source_payload),
                checksum_sha256=source_sha,
                source_snapshot={},
                status="processing",
            )
        )
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=organization_id,
                execution_type=VisualProducerAdapter.execution_type,
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="pending",
                input_payload={
                    "source_reference": f"s3://{bucket}/{source_key}",
                    "declared_media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "original_file_name": "embedded-image.docx",
                    "options": {"visual_understanding": {"enabled": True, "profile": "balanced"}},
                },
                policy_snapshot={},
                metrics={},
            )
        )
        db.commit()
    finally:
        db.close()

    adapter = VisualProducerAdapter(RuntimeVisualEnrichmentProducer.from_environment(S3SourceAcquisitionService()))
    registry = RuntimeAdapterRegistry()
    registry.register(adapter)
    worker = CheckpointRuntimeWorker(SessionLocal, registry, worker_id="worker-visual-producer-e2e")
    claimed = worker.run_once(organization_id, execution_id=execution_id)

    db = SessionLocal()
    try:
        execution = db.get(RuntimeExecution, execution_id)
        artifact = adapter.artifact or {}
        items = list(artifact.get("items", []))
        first_visual = items[0].get("visual", {}) if items else {}
        checks = {
            "work_item_claimed": claimed is not None,
            "execution_succeeded": execution.status == "succeeded",
            "visual_connected": execution.metrics.get("visual_enrichment_connected") is True,
            "visual_item_count": execution.metrics.get("visual_enrichment_item_count") == 1,
            "artifact_schema_valid": artifact.get("schema") == "visual-enrichment/v1",
            "embedded_image_extracted": len(items) == 1,
            "visual_understanding_succeeded": first_visual.get("status") == "succeeded",
            "provider_traceability": first_visual.get("provider_key") == "deterministic-local-vision",
            "source_provenance_preserved": items[0].get("source_kind") == "docx" if items else False,
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_id": str(execution_id),
                    "source_object": source_key,
                    "provider_key": first_visual.get("provider_key"),
                    "database_evidence_retained": True,
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
        with contextlib.suppress(Exception):
            s3.delete_object(Bucket=bucket, Key=source_key)

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
