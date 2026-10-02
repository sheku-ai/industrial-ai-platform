from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import UTC, datetime

import boto3
from sqlalchemy import select

from app.core.config import get_settings
from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.runtime import RuntimeExecutionArtifact


class VisualEnrichmentPublicationService:
    """Publishes visual enrichment output and records verified runtime evidence."""

    def __init__(self, session_factory, *, client=None) -> None:
        self._session_factory = session_factory
        settings = get_settings()
        self._bucket = settings.object_storage_bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            use_ssl=settings.object_storage_secure,
        )

    def publish(
        self,
        *,
        organization_id,
        execution_id,
        attempt_id,
        document_version_id,
        processing_revision_id,
        artifact: dict,
    ):
        payload = json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()

        revision = str(processing_revision_id or "unscoped")
        key = f"document-versions/{document_version_id}/revisions/{revision}/visual-enrichment.json"
        storage_uri = f"s3://{self._bucket}/{key}"

        session = self._session_factory()
        try:
            existing = session.scalar(
                select(RuntimeExecutionArtifact).where(
                    RuntimeExecutionArtifact.organization_id == organization_id,
                    RuntimeExecutionArtifact.execution_id == execution_id,
                    RuntimeExecutionArtifact.attempt_id == attempt_id,
                    RuntimeExecutionArtifact.artifact_type == "visual_enrichment",
                    RuntimeExecutionArtifact.checksum_sha256 == checksum,
                )
            )
            if existing is not None:
                return existing.id
        finally:
            session.close()

        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            Metadata={"sha256": checksum},
        )

        now = datetime.now(UTC)
        session = self._session_factory()
        try:
            runtime_artifact = RuntimeExecutionArtifact(
                organization_id=organization_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                artifact_type="visual_enrichment",
                storage_uri=storage_uri,
                media_type="application/json",
                checksum_sha256=checksum,
                size_bytes=len(payload),
                metadata_={
                    "schema": artifact.get("schema"),
                    "document_version_id": str(document_version_id),
                    "processing_revision_id": (str(processing_revision_id) if processing_revision_id else None),
                    "item_count": len(artifact.get("items", [])),
                },
                status="verified",
                created_at=now,
                updated_at=now,
            )
            session.add(runtime_artifact)
            session.flush()

            session.add(
                RuntimeArtifactPublication(
                    organization_id=organization_id,
                    execution_id=execution_id,
                    artifact_id=runtime_artifact.id,
                    attempt_id=attempt_id,
                    publication_number=1,
                    storage_uri=storage_uri,
                    media_type="application/json",
                    checksum_sha256=checksum,
                    size_bytes=len(payload),
                    status="verified",
                    published_at=now,
                    verified_at=now,
                    error_code=None,
                    metadata_={"schema": artifact.get("schema")},
                    created_at=now,
                )
            )

            session.commit()
            return runtime_artifact.id
        except Exception:
            session.rollback()
            with contextlib.suppress(Exception):
                self._client.delete_object(
                    Bucket=self._bucket,
                    Key=key,
                )
            raise
        finally:
            session.close()
