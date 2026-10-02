import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.models.runtime import RuntimeExecution
from app.services.object_storage_reader import S3CompatibleSourceObjectReader
from app.services.runtime_lifecycle import RuntimeLifecycleService
from app.workers.bootstrap_runtime import build_checkpoint_worker

PLACEHOLDER_VALUES = {
    "<ACCESS_KEY_REAL>",
    "<SECRET_KEY_REAL>",
    "your-access-key",
    "your-secret-key",
}


def _validate_settings(settings):
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL is required")
    if not settings.object_storage_endpoint_url:
        raise SystemExit("OBJECT_STORAGE_ENDPOINT_URL is required")
    if not settings.object_storage_bucket:
        raise SystemExit("OBJECT_STORAGE_BUCKET is required")
    if not settings.object_storage_access_key or settings.object_storage_access_key in PLACEHOLDER_VALUES:
        raise SystemExit("OBJECT_STORAGE_ACCESS_KEY must contain a real credential")
    if not settings.object_storage_secret_key or settings.object_storage_secret_key in PLACEHOLDER_VALUES:
        raise SystemExit("OBJECT_STORAGE_SECRET_KEY must contain a real credential")


def _client(settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        use_ssl=settings.object_storage_secure,
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def _preflight(client, bucket):
    try:
        client.head_bucket(Bucket=bucket)
    except EndpointConnectionError as exc:
        raise SystemExit(f"object storage endpoint is unreachable: {exc.endpoint_url}") from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        raise SystemExit(f"object storage bucket preflight failed: {code}") from exc
    except BotoCoreError as exc:
        raise SystemExit(f"object storage preflight failed: {exc}") from exc


def _seed(session, client, bucket):
    suffix = uuid4().hex[:12]
    organization = Organization(
        slug=f"smoke-{suffix}",
        name=f"Runtime smoke {suffix}",
        status="active",
        config={"smoke": True, "retention_class": "runtime_validation"},
    )
    session.add(organization)
    session.flush()

    document = DocumentRecord(
        organization_id=organization.id,
        title="Generic ingestion runtime smoke",
        source_type="object_storage",
        source_ref={},
        metadata_json={"smoke": True},
        classification={},
        status="registered",
    )
    session.add(document)
    session.flush()

    content = b"Industrial AI Platform productive ingestion runtime smoke.\nPostgreSQL is the source of truth.\n"
    checksum = hashlib.sha256(content).hexdigest()
    version = DocumentVersion(
        organization_id=organization.id,
        document_record_id=document.id,
        version_number=1,
        content_type="text/plain",
        file_name="runtime-smoke.txt",
        size_bytes=len(content),
        checksum_sha256=checksum,
        object_store_provider="s3-compatible",
        object_store_bucket=bucket,
        object_store_key="pending",
        source_snapshot={"smoke": True, "retention_class": "runtime_validation"},
        status="registered",
    )
    session.add(version)
    session.flush()

    key = f"{organization.id}/{document.id}/{version.id}/runtime-smoke.txt"
    version.object_store_key = key
    document.source_ref = {"object_storage": {"bucket": bucket, "key": key}}

    profile = IngestionPipelineProfile(
        organization_id=organization.id,
        code="runtime-smoke",
        name="Runtime smoke profile",
        revision="smoke-v1",
        enabled=True,
        deployment_edition="community",
        default_adapter_key="platform.text.plain",
        adapter_policies=[
            {
                "adapter_key": "platform.text.plain",
                "enabled": True,
                "priority": 100,
                "allowed_media_types": ["text/plain"],
            }
        ],
        adapter_versions={"platform.text.plain": "1.0.0"},
        adapter_settings={"platform.text.plain": {}},
    )
    session.add(profile)
    session.flush()

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType="text/plain",
        Metadata={"sha256": checksum, "smoke": "true"},
    )

    execution, _ = RuntimeLifecycleService(session).create_or_get(
        organization_id=organization.id,
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=version.id,
        idempotency_key=f"smoke:{suffix}",
        requested_by="runtime-smoke",
        correlation_id=f"smoke-{suffix}",
        priority=0,
        input_payload={
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "source_reference": f"s3://{bucket}/{key}",
            "declared_media_type": "text/plain",
            "original_file_name": version.file_name,
            "content_length": len(content),
            "checksum_sha256": checksum,
            "pipeline_profile_id": str(profile.id),
            "adapter_hint": "platform.text.plain",
            "metadata": {"smoke": True},
            "options": {},
        },
        policy_snapshot={
            "pipeline_profile_id": str(profile.id),
            "pipeline_profile_revision": profile.revision,
            "deployment_edition": profile.deployment_edition,
            "smoke": True,
        },
    )
    session.commit()
    return {
        "organization_id": organization.id,
        "document_id": document.id,
        "document_version_id": version.id,
        "profile_id": profile.id,
        "execution_id": execution.id,
        "bucket": bucket,
        "key": key,
    }


def _verify(session, identifiers):
    execution = session.scalar(select(RuntimeExecution).where(RuntimeExecution.id == identifiers["execution_id"]))
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == identifiers["document_version_id"]))
    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.document_version_id == identifiers["document_version_id"])
            .order_by(Chunk.chunk_index)
        )
    )
    fts_count = session.scalar(
        text(
            "select count(*) from documents.chunks where document_version_id = :version_id and fts_vector is not null"
        ),
        {"version_id": str(identifiers["document_version_id"])},
    )

    if execution is None or execution.status != "succeeded":
        raise RuntimeError(f"runtime execution did not succeed: {getattr(execution, 'status', None)}")
    if version is None or version.status != "indexed":
        raise RuntimeError(f"document version was not indexed: {getattr(version, 'status', None)}")
    if not chunks:
        raise RuntimeError("ingestion produced no chunks")
    if fts_count != len(chunks):
        raise RuntimeError("not all chunks have lexical vectors")

    return {
        "status": "passed",
        "organization_id": str(identifiers["organization_id"]),
        "document_id": str(identifiers["document_id"]),
        "document_version_id": str(identifiers["document_version_id"]),
        "execution_id": str(identifiers["execution_id"]),
        "execution_status": execution.status,
        "document_version_status": version.status,
        "chunk_count": len(chunks),
        "fts_vector_count": int(fts_count),
        "metrics": dict(execution.metrics or {}),
        "retention": {
            "database_records": "retained",
            "source_object": "retained",
            "reason": "runtime execution events are append-only audit records",
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run a real PostgreSQL and object-storage ingestion smoke")
    parser.parse_args()

    settings = get_settings()
    _validate_settings(settings)
    client = _client(settings)
    _preflight(client, settings.object_storage_bucket)
    reader = S3CompatibleSourceObjectReader(client, required_bucket=settings.object_storage_bucket)

    session = SessionLocal()
    try:
        identifiers = _seed(session, client, settings.object_storage_bucket)
        worker = build_checkpoint_worker(
            SessionLocal,
            reader,
            "runtime-smoke-worker",
            Path(settings.ingestion_workspace_root),
            settings.ingestion_max_source_bytes,
        )
        item = worker.run_once(
            identifiers["organization_id"],
            execution_type="document.ingestion",
        )
        if item is None or item.execution_id != identifiers["execution_id"]:
            raise RuntimeError("smoke execution was not claimed")
        session.expire_all()
        print(json.dumps(_verify(session, identifiers), indent=2, sort_keys=True))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
