from __future__ import annotations

import hashlib
import io
import json
import os
import time
import uuid

import boto3
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.models.runtime import RuntimeExecution
from app.services.runtime_lifecycle import RuntimeLifecycleService


def build_pdf() -> bytes:
    output = io.BytesIO()
    encryption = StandardEncryption("smoke-password", canPrint=0, canModify=0, canCopy=0, canAnnotate=0)
    pdf = canvas.Canvas(output, encrypt=encryption)
    pdf.drawString(72, 720, "PROTECTED_PDF_SENTINEL_25_6A")
    pdf.save()
    return output.getvalue()


def main() -> int:
    settings = get_settings()
    token = uuid.uuid4().hex[:12]
    content = build_pdf()
    checksum = hashlib.sha256(content).hexdigest()
    bucket = settings.object_storage_bucket or "industrial-ai-smoke"
    key = f"smoke/{token}/protected.pdf"
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        use_ssl=settings.object_storage_secure,
    )
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType="application/pdf")

    session = SessionLocal()
    try:
        org = Organization(slug=f"smoke-protected-{token}", name=f"Smoke Protected {token}", status="active", config={})
        session.add(org)
        session.flush()
        profile = IngestionPipelineProfile(
            organization_id=org.id,
            code=f"smoke-protected-{token}",
            name="Smoke Protected PDF",
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
            external_reference=f"smoke-protected:{token}",
            title=f"Smoke Protected {token}",
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
            file_name="protected.pdf",
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
            idempotency_key=f"smoke:protected:{token}",
            requested_by="smoke",
            correlation_id=f"smoke-protected-{token}",
            priority=10,
            input_payload={
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "source_reference": f"s3://{bucket}/{key}",
                "declared_media_type": "application/pdf",
                "original_file_name": "protected.pdf",
                "content_length": len(content),
                "checksum_sha256": checksum,
                "pipeline_profile_id": str(profile.id),
                "adapter_hint": "platform.pdf.text_layer",
                "metadata": {"smoke": True},
                "options": {},
            },
            policy_snapshot={
                "pipeline_profile_id": str(profile.id),
                "pipeline_profile_revision": "1",
                "deployment_edition": "community",
            },
        )
        session.commit()
        execution_id, version_id, _org_id = execution.id, version.id, org.id
    finally:
        session.close()

    deadline = time.monotonic() + int(os.getenv("SMOKE_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        session = SessionLocal()
        try:
            execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
            if execution and execution.status in {"failed", "dead_lettered", "succeeded"}:
                break
        finally:
            session.close()
        time.sleep(1)

    session = SessionLocal()
    try:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id))
        review = session.scalar(select(DocumentReviewCase).where(DocumentReviewCase.document_version_id == version_id))
        event_count = (
            session.scalar(
                select(func.count())
                .select_from(DocumentReviewEvent)
                .where(DocumentReviewEvent.review_case_id == review.id)
            )
            if review
            else 0
        )
        chunk_count = session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_version_id == version_id)
        )
        serialized = json.dumps(
            {
                "execution": dict(execution.metrics or {}) if execution else {},
                "snapshot": dict(version.source_snapshot or {}) if version else {},
                "review": dict(review.metadata_json or {}) if review else {},
            }
        )
        passed = bool(
            execution
            and execution.status != "succeeded"
            and version
            and version.status == "pending_human_review"
            and review
            and review.status == "pending_human_review"
            and review.reason == "password_required"
            and event_count >= 1
            and chunk_count == 0
            and "smoke-password" not in serialized
        )
        payload = {
            "passed": passed,
            "execution_status": execution.status if execution else None,
            "document_version_status": version.status if version else None,
            "review_case_id": str(review.id) if review else None,
            "review_status": review.status if review else None,
            "review_reason": review.reason if review else None,
            "review_event_count": event_count,
            "chunk_count": chunk_count,
            "credential_value_persisted": "smoke-password" in serialized,
            "error_code": execution.error_code if execution else None,
            "error_message": execution.error_message if execution else None,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if passed else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
