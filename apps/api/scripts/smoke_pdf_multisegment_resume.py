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
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.models.segment_plan import IngestionSegment, IngestionSegmentPlan
from app.services.runtime_lifecycle import RuntimeLifecycleService

S1 = "SMOKE_MULTI_PAGE_1"
S2 = "SMOKE_MULTI_PAGE_2"


def pdf_bytes():
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    pdf.drawString(72, 720, S1)
    pdf.showPage()
    pdf.drawString(72, 720, S2)
    pdf.save()
    return out.getvalue()


def main():
    settings = get_settings()
    token = uuid.uuid4().hex[:12]
    content = pdf_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    bucket = settings.object_storage_bucket or os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    key = f"smoke/{token}/multi.pdf"
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
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
        org = Organization(slug=f"smoke-multi-{token}", name=f"Smoke Multi {token}", status="active", config={})
        session.add(org)
        session.flush()
        profile = IngestionPipelineProfile(
            organization_id=org.id,
            code=f"smoke-multi-{token}",
            name="Smoke Multi",
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
        doc = DocumentRecord(
            organization_id=org.id,
            external_reference=f"smoke-multi:{token}",
            title=f"Smoke Multi {token}",
            source_type="object_storage",
            source_ref={},
            metadata_json={},
            classification={},
            status="registered",
        )
        session.add(doc)
        session.flush()
        version = DocumentVersion(
            organization_id=org.id,
            document_record_id=doc.id,
            version_number=1,
            content_type="application/pdf",
            file_name="multi.pdf",
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
            idempotency_key=f"smoke:multi:{token}",
            requested_by="smoke",
            correlation_id=f"smoke-multi-{token}",
            priority=10,
            input_payload={
                "document_id": str(doc.id),
                "document_version_id": str(version.id),
                "source_reference": f"s3://{bucket}/{key}",
                "declared_media_type": "application/pdf",
                "original_file_name": "multi.pdf",
                "content_length": len(content),
                "checksum_sha256": checksum,
                "pipeline_profile_id": str(profile.id),
                "adapter_hint": "platform.pdf.text_layer",
                "metadata": {},
                "options": {"page_count_hint": 2, "pages_per_segment": 1},
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
            execution = session.get(RuntimeExecution, execution_id)
            if execution and execution.status in {"succeeded", "failed", "cancelled", "dead_lettered"}:
                break
        finally:
            session.close()
        time.sleep(1)

    session = SessionLocal()
    try:
        execution = session.get(RuntimeExecution, execution_id)
        version = session.get(DocumentVersion, version_id)
        attempts = list(
            session.scalars(
                select(RuntimeExecutionAttempt)
                .where(RuntimeExecutionAttempt.execution_id == execution_id)
                .order_by(RuntimeExecutionAttempt.attempt_number)
            ).all()
        )
        plan = session.scalar(select(IngestionSegmentPlan).where(IngestionSegmentPlan.execution_id == execution_id))
        segments = (
            list(
                session.scalars(
                    select(IngestionSegment)
                    .where(IngestionSegment.plan_id == plan.id)
                    .order_by(IngestionSegment.ordinal)
                ).all()
            )
            if plan
            else []
        )
        chunks = list(
            session.scalars(
                select(Chunk)
                .where(Chunk.organization_id == org_id, Chunk.document_version_id == version_id)
                .order_by(Chunk.chunk_index)
            ).all()
        )
        metrics = dict(execution.metrics or {}) if execution else {}
        passed = bool(
            execution
            and execution.status == "succeeded"
            and version
            and version.status == "indexed"
            and len(attempts) == 2
            and [a.status for a in attempts] == ["succeeded", "succeeded"]
            and len(segments) == 2
            and [s.status for s in segments] == ["completed", "completed"]
            and [s.attempt_count for s in segments] == [1, 1]
            and len(chunks) == 2
            and [c.chunk_index for c in chunks] == [0, 1]
            and S1 in chunks[0].text
            and S2 in chunks[1].text
            and all(c.fts_vector is not None for c in chunks)
            and metrics.get("segment_checkpoint_completed") == 2
            and metrics.get("segment_resume_required") is False
        )
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_status": execution.status if execution else None,
                    "document_version_status": version.status if version else None,
                    "runtime_attempt_count": len(attempts),
                    "runtime_attempt_statuses": [a.status for a in attempts],
                    "segment_statuses": [s.status for s in segments],
                    "segment_attempt_counts": [s.attempt_count for s in segments],
                    "chunk_indexes": [c.chunk_index for c in chunks],
                    "fts_ready": bool(chunks) and all(c.fts_vector is not None for c in chunks),
                    "metrics": metrics,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
