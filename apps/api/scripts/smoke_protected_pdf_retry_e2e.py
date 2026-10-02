from __future__ import annotations

import hashlib
import io
import json
import os
import time
import uuid

import boto3
import httpx
import psycopg
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
from app.services.secret_store import SecretNotFound
from app.services.secret_store_runtime import get_secret_store

CREDENTIAL = "smoke-password"
SENTINEL = "PROTECTED_PDF_RETRY_SENTINEL_25_6A_8_5"


def build_pdf() -> bytes:
    output = io.BytesIO()
    encryption = StandardEncryption(CREDENTIAL, canPrint=0, canModify=0, canCopy=0, canAnnotate=0)
    pdf = canvas.Canvas(output, encrypt=encryption)
    pdf.drawString(72, 720, SENTINEL)
    pdf.save()
    return output.getvalue()


def wait_for_execution(execution_id: uuid.UUID, timeout_seconds: int) -> RuntimeExecution | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        session = SessionLocal()
        try:
            execution = session.get(RuntimeExecution, execution_id)
            if execution and execution.status in {"failed", "dead_lettered", "succeeded", "cancelled"}:
                return execution
        finally:
            session.close()
        time.sleep(1)
    return None


def database_contains(value: str) -> bool:
    database_url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    pattern = f"%{value}%"
    queries = (
        "SELECT EXISTS (SELECT 1 FROM documents.document_review_cases t WHERE row_to_json(t)::text LIKE %s)",
        "SELECT EXISTS (SELECT 1 FROM documents.document_review_events t WHERE row_to_json(t)::text LIKE %s)",
        "SELECT EXISTS (SELECT 1 FROM core.runtime_executions t WHERE row_to_json(t)::text LIKE %s)",
        "SELECT EXISTS (SELECT 1 FROM documents.document_versions t WHERE row_to_json(t)::text LIKE %s)",
    )
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        for query in queries:
            try:
                cursor.execute(query, (pattern,))
                if bool(cursor.fetchone()[0]):
                    return True
            except psycopg.errors.UndefinedTable:
                connection.rollback()
    return False


def main() -> int:
    settings = get_settings()
    timeout_seconds = int(os.getenv("SMOKE_TIMEOUT_SECONDS", "180"))
    api_base_url = os.getenv("SMOKE_API_BASE_URL", "http://api:8000/api")
    token = uuid.uuid4().hex[:12]
    content = build_pdf()
    checksum = hashlib.sha256(content).hexdigest()
    bucket = settings.object_storage_bucket or "industrial-ai-smoke"
    key = f"smoke/{token}/protected-retry.pdf"

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
        organization = Organization(
            slug=f"smoke-protected-retry-{token}", name=f"Smoke Protected Retry {token}", status="active", config={}
        )
        session.add(organization)
        session.flush()
        profile = IngestionPipelineProfile(
            organization_id=organization.id,
            code=f"smoke-protected-retry-{token}",
            name="Smoke Protected PDF Retry",
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
            organization_id=organization.id,
            external_reference=f"smoke-protected-retry:{token}",
            title=f"Smoke Protected Retry {token}",
            source_type="object_storage",
            source_ref={},
            metadata_json={"smoke": True},
            classification={},
            status="registered",
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            organization_id=organization.id,
            document_record_id=document.id,
            version_number=1,
            content_type="application/pdf",
            file_name="protected-retry.pdf",
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
            organization_id=organization.id,
            execution_type="document.ingestion",
            subject_type="document_version",
            subject_id=version.id,
            idempotency_key=f"smoke:protected-retry:{token}",
            requested_by="smoke",
            correlation_id=f"smoke-protected-retry-{token}",
            priority=10,
            input_payload={
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "source_reference": f"s3://{bucket}/{key}",
                "declared_media_type": "application/pdf",
                "original_file_name": "protected-retry.pdf",
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
        initial_execution_id = execution.id
        version_id = version.id
        organization_id = organization.id
    finally:
        session.close()

    initial_execution = wait_for_execution(initial_execution_id, timeout_seconds)
    session = SessionLocal()
    try:
        review = session.scalar(select(DocumentReviewCase).where(DocumentReviewCase.document_version_id == version_id))
        if review is None:
            raise RuntimeError("protected document review case was not created")
        review_id = review.id
    finally:
        session.close()

    with httpx.Client(base_url=api_base_url, timeout=30) as client:
        response = client.post(
            f"/document-reviews/{review_id}/credentials",
            json={"credential": CREDENTIAL, "actor_subject": "smoke", "ttl_seconds": 120},
        )
        response.raise_for_status()

        session = SessionLocal()
        try:
            secret_reference = session.get(DocumentReviewCase, review_id).secret_reference
        finally:
            session.close()

        response = client.post(
            f"/document-reviews/{review_id}/retry",
            json={"actor_subject": "smoke"},
        )
        response.raise_for_status()
        retry_execution_id = uuid.UUID(response.json()["runtime_execution_id"])

    retry_execution = wait_for_execution(retry_execution_id, timeout_seconds)
    secret_consumed = False
    try:
        get_secret_store().inspect(secret_reference)
    except SecretNotFound:
        secret_consumed = True

    session = SessionLocal()
    try:
        version = session.get(DocumentVersion, version_id)
        review = session.get(DocumentReviewCase, review_id)
        chunks = list(
            session.scalars(
                select(Chunk)
                .where(Chunk.organization_id == organization_id, Chunk.document_version_id == version_id)
                .order_by(Chunk.chunk_index)
            ).all()
        )
        event_count = int(
            session.scalar(
                select(func.count())
                .select_from(DocumentReviewEvent)
                .where(DocumentReviewEvent.review_case_id == review_id)
            )
            or 0
        )
        sentinel_found = any(SENTINEL in chunk.text for chunk in chunks)
        fts_ready = bool(chunks) and all(chunk.fts_vector is not None for chunk in chunks)
        credential_value_persisted = database_contains(CREDENTIAL)
        passed = bool(
            initial_execution
            and initial_execution.status != "succeeded"
            and retry_execution
            and retry_execution.status == "succeeded"
            and version
            and version.status == "indexed"
            and review
            and review.status == "resolved"
            and review.secret_reference is None
            and chunks
            and sentinel_found
            and fts_ready
            and event_count >= 4
            and secret_consumed
            and not credential_value_persisted
        )
        print(
            json.dumps(
                {
                    "passed": passed,
                    "initial_execution_status": initial_execution.status if initial_execution else None,
                    "retry_execution_status": retry_execution.status if retry_execution else None,
                    "document_version_status": version.status if version else None,
                    "review_status": review.status if review else None,
                    "review_event_count": event_count,
                    "chunk_count": len(chunks),
                    "sentinel_found": sentinel_found,
                    "fts_ready": fts_ready,
                    "secret_consumed": secret_consumed,
                    "credential_value_persisted": credential_value_persisted,
                    "retry_error_code": retry_execution.error_code if retry_execution else None,
                    "retry_error_message": retry_execution.error_message if retry_execution else None,
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
