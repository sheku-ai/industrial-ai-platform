from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

import boto3
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.models.runtime import RuntimeExecution
from app.services.runtime_lifecycle import RuntimeLifecycleService

SENTINEL = "SMOKE_TEXT_SENTINEL_25_6A"


def main() -> int:
    settings = get_settings()
    endpoint = settings.object_storage_endpoint_url or os.getenv("OBJECT_STORAGE_ENDPOINT_URL")
    bucket = settings.object_storage_bucket or os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    if not endpoint:
        raise RuntimeError("object storage endpoint is not configured")

    token = uuid.uuid4().hex[:12]
    content = f"{SENTINEL}\n\nSmoke {token}\n".encode()
    checksum = hashlib.sha256(content).hexdigest()
    key = f"smoke/{token}/sample.txt"

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
    s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType="text/plain")

    session = SessionLocal()
    try:
        org = Organization(slug=f"smoke-{token}", name=f"Smoke {token}", status="active", config={})
        session.add(org)
        session.flush()
        profile = IngestionPipelineProfile(
            organization_id=org.id,
            code=f"smoke-{token}",
            name="Smoke Text",
            revision="1",
            enabled=True,
            deployment_edition="community",
            default_adapter_key="platform.text.plain",
            adapter_policies=[
                {
                    "adapter_key": "platform.text.plain",
                    "enabled": True,
                    "priority": 1,
                    "allowed_media_types": ["text/plain"],
                }
            ],
            adapter_versions={"platform.text.plain": "1.0.0"},
            adapter_settings={
                "platform.text.plain": {"encoding": "utf-8", "split_on_blank_lines": True, "max_units": 100}
            },
        )
        session.add(profile)
        doc = DocumentRecord(
            organization_id=org.id,
            external_reference=f"smoke:{token}",
            title=f"Smoke Text {token}",
            source_type="object_storage",
            source_ref={},
            metadata_json={"smoke": True},
            classification={},
            status="registered",
        )
        session.add(doc)
        session.flush()
        version = DocumentVersion(
            organization_id=org.id,
            document_record_id=doc.id,
            version_number=1,
            content_type="text/plain",
            file_name="sample.txt",
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
            idempotency_key=f"smoke:text:{token}",
            requested_by="smoke",
            correlation_id=f"smoke-{token}",
            priority=10,
            input_payload={
                "document_id": str(doc.id),
                "document_version_id": str(version.id),
                "source_reference": f"s3://{bucket}/{key}",
                "declared_media_type": "text/plain",
                "original_file_name": "sample.txt",
                "content_length": len(content),
                "checksum_sha256": checksum,
                "pipeline_profile_id": str(profile.id),
                "adapter_hint": "platform.text.plain",
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
        execution_id, version_id, org_id = execution.id, version.id, org.id
    finally:
        session.close()

    deadline = time.monotonic() + int(os.getenv("SMOKE_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        session = SessionLocal()
        try:
            execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
            if execution and execution.status in {"succeeded", "failed", "cancelled"}:
                break
        finally:
            session.close()
        time.sleep(1)

    session = SessionLocal()
    try:
        execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == execution_id))
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id))
        chunks = list(
            session.scalars(
                select(Chunk)
                .where(Chunk.organization_id == org_id, Chunk.document_version_id == version_id)
                .order_by(Chunk.chunk_index)
            ).all()
        )
        passed = bool(
            execution
            and execution.status == "succeeded"
            and version
            and version.status == "indexed"
            and chunks
            and any(SENTINEL in (c.text or "") for c in chunks)
            and all(c.fts_vector is not None for c in chunks)
        )
        payload = {
            "passed": passed,
            "execution_id": str(execution_id),
            "execution_status": execution.status if execution else None,
            "document_version_status": version.status if version else None,
            "chunk_count": len(chunks),
            "sentinel_found": any(SENTINEL in (c.text or "") for c in chunks),
            "fts_ready": bool(chunks) and all(c.fts_vector is not None for c in chunks),
            "metrics": dict(execution.metrics or {}) if execution else {},
            "error_code": execution.error_code if execution else None,
            "error_message": execution.error_message if execution else None,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if passed else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
