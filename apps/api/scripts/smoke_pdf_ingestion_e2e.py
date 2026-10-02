from __future__ import annotations

import hashlib
import io
import json
import os
import time
import uuid

import boto3
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution
from app.services.runtime_lifecycle import RuntimeLifecycleService

PAGE_1 = "SMOKE_PDF_SENTINEL_PAGE_1_25_6A"
PAGE_2 = "SMOKE_PDF_SENTINEL_PAGE_2_25_6A"


def build_pdf() -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(72, 720, PAGE_1)
    pdf.showPage()
    pdf.drawString(72, 720, PAGE_2)
    pdf.save()
    return output.getvalue()


def main() -> int:
    settings = get_settings()
    endpoint = settings.object_storage_endpoint_url or os.getenv("OBJECT_STORAGE_ENDPOINT_URL")
    bucket = settings.object_storage_bucket or os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    if not endpoint:
        raise RuntimeError("object storage endpoint is not configured")

    token = uuid.uuid4().hex[:12]
    content = build_pdf()
    checksum = hashlib.sha256(content).hexdigest()
    key = f"smoke/{token}/sample.pdf"

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key or os.getenv("OBJECT_STORAGE_ACCESS_KEY"),
        aws_secret_access_key=settings.object_storage_secret_key or os.getenv("OBJECT_STORAGE_SECRET_KEY"),
        use_ssl=settings.object_storage_secure,
    )
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType="application/pdf", Metadata={"sha256": checksum})

    session = SessionLocal()
    try:
        org = Organization(slug=f"smoke-pdf-{token}", name=f"Smoke PDF {token}", status="active", config={})
        session.add(org)
        session.flush()
        profile = IngestionPipelineProfile(
            organization_id=org.id,
            code=f"smoke-pdf-{token}",
            name="Smoke PDF",
            revision="1",
            enabled=True,
            deployment_edition="community",
            default_adapter_key="platform.pdf.text_layer",
            adapter_policies=[
                {
                    "adapter_key": "platform.pdf.text_layer",
                    "enabled": True,
                    "priority": 1,
                    "allowed_media_types": ["application/pdf"],
                }
            ],
            adapter_versions={"platform.pdf.text_layer": "1.0.0"},
            adapter_settings={"platform.pdf.text_layer": {"max_pages": 100}},
        )
        session.add(profile)
        document = DocumentRecord(
            organization_id=org.id,
            external_reference=f"smoke-pdf:{token}",
            title=f"Smoke PDF {token}",
            source_type="object_storage",
            source_ref={},
            metadata_json={"smoke": True},
            classification={},
            status="registered",
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            organization_id=org.id,
            document_record_id=document.id,
            version_number=1,
            content_type="application/pdf",
            file_name="sample.pdf",
            size_bytes=len(content),
            checksum_sha256=checksum,
            object_store_provider="s3-compatible",
            object_store_bucket=bucket,
            object_store_key=key,
            source_snapshot={"source_reference": f"s3://{bucket}/{key}"},
            status="registered",
        )
        session.add(version)
        session.flush()
        execution, _ = RuntimeLifecycleService(session).create_or_get(
            organization_id=org.id,
            execution_type="document.ingestion",
            subject_type="document_version",
            subject_id=version.id,
            idempotency_key=f"smoke:pdf:{token}",
            requested_by="smoke",
            correlation_id=f"smoke-pdf-{token}",
            priority=10,
            input_payload={
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "source_reference": f"s3://{bucket}/{key}",
                "declared_media_type": "application/pdf",
                "original_file_name": "sample.pdf",
                "content_length": len(content),
                "checksum_sha256": checksum,
                "pipeline_profile_id": str(profile.id),
                "adapter_hint": "platform.pdf.text_layer",
                "metadata": {"smoke": True},
                "options": {"page_count_hint": 2},
            },
            policy_snapshot={
                "pipeline_profile_id": str(profile.id),
                "pipeline_profile_revision": "1",
                "deployment_edition": "community",
            },
        )
        session.commit()
        execution_id, version_id, org_id = execution.id, version.id, org.id
    finally:
        session.close()

    deadline = time.monotonic() + int(os.getenv("SMOKE_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        session = SessionLocal()
        try:
            execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
            if execution and execution.status in {"succeeded", "failed", "cancelled", "dead_lettered"}:
                break
        finally:
            session.close()
        time.sleep(1)

    session = SessionLocal()
    try:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id))
        revision = session.scalar(
            select(ProcessingRevision).where(ProcessingRevision.runtime_execution_id == execution_id)
        )
        chunks = list(
            session.scalars(
                select(Chunk)
                .where(Chunk.organization_id == org_id, Chunk.document_version_id == version_id)
                .order_by(Chunk.chunk_index)
            ).all()
        )
        page_numbers = [chunk.section_ref.get("page_number") for chunk in chunks]
        page_1_found = any(PAGE_1 in chunk.text for chunk in chunks)
        page_2_found = any(PAGE_2 in chunk.text for chunk in chunks)
        fts_ready = bool(chunks) and all(chunk.fts_vector is not None for chunk in chunks)
        metrics = dict(execution.metrics or {}) if execution else {}
        adapter_metrics_propagated = bool(
            metrics.get("adapter_metrics_propagated") is True
            and metrics.get("page_count") == 2
            and metrics.get("source_bytes") == len(content)
            and metrics.get("encrypted") is False
            and metrics.get("ocr_used") is False
        )
        processing_revision_connected = bool(
            revision
            and revision.status == "completed"
            and revision.completed_at is not None
            and revision.document_version_id == version_id
            and revision.runtime_execution_id == execution_id
            and revision.pipeline_profile_revision == "1"
            and revision.adapter_key == "platform.pdf.text_layer"
            and revision.adapter_version == "1.0.0"
            and revision.source_checksum_sha256 == checksum
            and revision.content_unit_count == 2
            and revision.chunk_count == 2
            and metrics.get("processing_revision_connected") is True
            and metrics.get("processing_revision_id") == str(revision.id)
        )
        page_range_connected = bool(
            metrics.get("segment_plan_strategy") == "pdf_page_range"
            and metrics.get("segment_range_unit") == "page"
            and metrics.get("segment_range_start") == 0
            and metrics.get("segment_range_end_exclusive") == 2
            and metrics.get("page_start") == 0
            and metrics.get("page_end_exclusive") == 2
            and metrics.get("pages_processed") == 2
        )
        passed = bool(
            execution
            and execution.status == "succeeded"
            and version
            and version.status == "indexed"
            and len(chunks) == 2
            and page_numbers == [1, 2]
            and page_1_found
            and page_2_found
            and fts_ready
            and metrics.get("adapter_key") == "platform.pdf.text_layer"
            and adapter_metrics_propagated
            and processing_revision_connected
            and page_range_connected
        )
        payload = {
            "passed": passed,
            "execution_id": str(execution_id),
            "execution_status": execution.status if execution else None,
            "document_version_status": version.status if version else None,
            "chunk_count": len(chunks),
            "page_numbers": page_numbers,
            "page_1_sentinel_found": page_1_found,
            "page_2_sentinel_found": page_2_found,
            "fts_ready": fts_ready,
            "adapter_metrics_propagated": adapter_metrics_propagated,
            "processing_revision_connected": processing_revision_connected,
            "page_range_connected": page_range_connected,
            "processing_revision_id": str(revision.id) if revision else None,
            "processing_revision_status": revision.status if revision else None,
            "processing_revision_content_unit_count": revision.content_unit_count if revision else None,
            "processing_revision_chunk_count": revision.chunk_count if revision else None,
            "page_count": metrics.get("page_count"),
            "source_bytes": metrics.get("source_bytes"),
            "encrypted": metrics.get("encrypted"),
            "ocr_used": metrics.get("ocr_used"),
            "metrics": metrics,
            "error_code": execution.error_code if execution else None,
            "error_message": execution.error_message if execution else None,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if passed else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
