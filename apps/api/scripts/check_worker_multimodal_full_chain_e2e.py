import contextlib
import hashlib
import io
import json
import os
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.db.session import SessionLocal
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


def build_pdf():
    image_buffer = io.BytesIO()
    image = Image.new("RGB", (240, 120), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((10, 10, 230, 110), outline="black", width=4)
    drawing.line((35, 60, 205, 60), fill="black", width=4)
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.setTitle("Generic multimodal ingestion evidence")
    pdf.drawString(72, 760, "Authoritative generic platform text for multimodal ingestion validation.")
    pdf.drawString(72, 740, "The text record must remain first in the final knowledge artifact.")
    pdf.drawImage(ImageReader(image_buffer), 72, 560, width=360, height=180, mask="auto")
    pdf.showPage()
    pdf.save()
    return output.getvalue()


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

    organization_id, document_id, version_id, execution_id, profile_id = [uuid.uuid4() for _ in range(5)]
    source_key = f"worker-multimodal-full-chain/{execution_id}/source.pdf"
    payload = build_pdf()
    checksum = hashlib.sha256(payload).hexdigest()
    s3.put_object(
        Bucket=bucket, Key=source_key, Body=payload, ContentType="application/pdf", Metadata={"sha256": checksum}
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"multimodal-full-chain-{uuid.uuid4().hex}",
                name="Multimodal Full Chain E2E",
                status="active",
                config={},
            )
        )
        db.add(
            IngestionPipelineProfile(
                id=profile_id,
                organization_id=organization_id,
                code="multimodal-full-chain",
                name="Multimodal Full Chain",
                revision="1",
                enabled=True,
                deployment_edition="community",
                default_adapter_key="platform.pdf.text_layer",
                adapter_policies=[
                    {
                        "adapter_key": "platform.pdf.text_layer",
                        "enabled": True,
                        "priority": 100,
                        "allowed_media_types": ["application/pdf"],
                    }
                ],
                adapter_versions={"platform.pdf.text_layer": "1.0.0"},
                adapter_settings={"platform.pdf.text_layer": {"max_pages": 10, "enable_ocr": False}},
            )
        )
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Multimodal Full Chain E2E",
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
                content_type="application/pdf",
                file_name="source.pdf",
                size_bytes=len(payload),
                checksum_sha256=checksum,
                source_snapshot={},
                status="processing",
            )
        )
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=organization_id,
                execution_type="document.ingestion",
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="pending",
                input_payload={
                    "document_id": str(document_id),
                    "document_version_id": str(version_id),
                    "source_reference": f"s3://{bucket}/{source_key}",
                    "declared_media_type": "application/pdf",
                    "original_file_name": "source.pdf",
                    "content_length": len(payload),
                    "checksum_sha256": checksum,
                    "pipeline_profile_id": str(profile_id),
                    "metadata": {},
                    "options": {
                        "visual_understanding": {
                            "enabled": True,
                            "profile": "balanced",
                        }
                    },
                },
                policy_snapshot={
                    "pipeline_profile_id": str(profile_id),
                    "pipeline_profile_revision": "1",
                    "deployment_edition": "community",
                },
                metrics={},
            )
        )
        db.commit()
    finally:
        db.close()

    registry = RuntimeAdapterRegistry()
    registry.register(build_document_ingestion_adapter(session_factory=SessionLocal))
    worker = CheckpointRuntimeWorker(SessionLocal, registry, worker_id="worker-multimodal-full-chain-e2e")
    claimed = worker.run_once(organization_id, execution_id=execution_id)

    db = SessionLocal()
    knowledge_key = None
    try:
        execution = db.get(RuntimeExecution, execution_id)
        attempt = db.scalar(select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id))
        version = db.get(DocumentVersion, version_id)
        chunks = list(
            db.scalars(select(Chunk).where(Chunk.document_version_id == version_id).order_by(Chunk.chunk_index)).all()
        )
        artifacts = list(
            db.scalars(
                select(RuntimeExecutionArtifact).where(RuntimeExecutionArtifact.execution_id == execution_id)
            ).all()
        )
        by_type = {artifact.artifact_type: artifact for artifact in artifacts}
        visual_artifact = by_type.get("visual_enrichment")
        knowledge_artifact = by_type.get("knowledge_ndjson")
        records = []
        if knowledge_artifact is not None:
            parsed = urlparse(knowledge_artifact.storage_uri)
            knowledge_key = parsed.path.lstrip("/")
            body = s3.get_object(Bucket=parsed.netloc, Key=knowledge_key)["Body"]
            try:
                records = [json.loads(line) for line in body.read().decode("utf-8").splitlines() if line.strip()]
            finally:
                body.close()
        modalities = [record.get("metadata", {}).get("content_modality") for record in records]
        visual_records = [
            record for record in records if record.get("metadata", {}).get("content_modality") == "visual_description"
        ]
        checks = {
            "work_item_claimed": claimed is not None,
            "execution_succeeded": execution.status == "succeeded",
            "attempt_succeeded": attempt is not None and attempt.status == "succeeded",
            "document_indexed": version.status == "indexed",
            "text_chunks_persisted": len(chunks) > 0,
            "visual_enrichment_published": visual_artifact is not None and visual_artifact.status == "verified",
            "knowledge_artifact_published": knowledge_artifact is not None and knowledge_artifact.status == "verified",
            "mixed_records": "text" in modalities and "visual_description" in modalities,
            "text_first": bool(modalities) and modalities[0] == "text",
            "provider_traceability": bool(visual_records)
            and visual_records[0].get("metadata", {}).get("provider_key") == "deterministic-local-vision",
            "visual_provenance_preserved": bool(visual_records)
            and visual_records[0].get("metadata", {}).get("source_kind") == "pdf",
            "runtime_metrics_persisted": execution.metrics.get("visual_enrichment_published") is True
            and bool(execution.metrics.get("knowledge_artifact_id")),
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_id": str(execution_id),
                    "document_version_id": str(version_id),
                    "artifact_types": sorted(by_type),
                    "record_count": len(records),
                    "modalities": modalities,
                    "database_evidence_retained": True,
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
        for key in (source_key, knowledge_key):
            if key:
                with contextlib.suppress(Exception):
                    s3.delete_object(Bucket=bucket, Key=key)

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
