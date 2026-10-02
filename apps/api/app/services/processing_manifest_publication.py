from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import boto3

from app.core.config import get_settings
from app.models.artifact_publication import RuntimeArtifactPublication
from app.models.runtime import RuntimeExecutionArtifact


class ProcessingManifestPublicationService:
    """Publishes a provider-neutral processing manifest and records its lifecycle."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        settings = get_settings()
        self._bucket = settings.object_storage_bucket
        self._client = boto3.client(
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
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        document_version_id: UUID,
        processing_revision_id: UUID | None,
        adapter_key: str,
        adapter_version: str,
        source_checksum_sha256: str | None,
        content_unit_count: int,
        chunk_count: int,
    ) -> UUID:
        manifest = {
            "schema_version": "1.0",
            "organization_id": str(organization_id),
            "execution_id": str(execution_id),
            "attempt_id": str(attempt_id),
            "document_version_id": str(document_version_id),
            "processing_revision_id": str(processing_revision_id) if processing_revision_id else None,
            "adapter": {"key": adapter_key, "version": adapter_version},
            "source_checksum_sha256": source_checksum_sha256,
            "content_unit_count": content_unit_count,
            "chunk_count": chunk_count,
        }
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
        key = f"runtime/{organization_id}/{execution_id}/{attempt_id}/processing-manifest.json"
        storage_uri = f"s3://{self._bucket}/{key}"

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
            artifact = RuntimeExecutionArtifact(
                organization_id=organization_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                artifact_type="processing_manifest",
                storage_uri=storage_uri,
                media_type="application/json",
                checksum_sha256=checksum,
                size_bytes=len(payload),
                metadata_={"schema_version": "1.0", "document_version_id": str(document_version_id)},
                status="published",
                created_at=now,
                updated_at=now,
            )
            session.add(artifact)
            session.flush()
            publication = RuntimeArtifactPublication(
                organization_id=organization_id,
                execution_id=execution_id,
                artifact_id=artifact.id,
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
                metadata_={"schema_version": "1.0"},
                created_at=now,
            )
            session.add(publication)
            session.commit()
            return artifact.id
        except Exception:
            session.rollback()
            with contextlib.suppress(Exception):
                self._client.delete_object(Bucket=self._bucket, Key=key)
            raise
        finally:
            session.close()
