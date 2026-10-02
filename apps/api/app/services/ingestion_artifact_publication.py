from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.models.runtime import RuntimeExecutionArtifact


class ArtifactObjectWriter(Protocol):
    def put(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        media_type: str,
        metadata: Mapping[str, str],
    ) -> None: ...


class S3CompatibleArtifactObjectWriter:
    def __init__(self, client) -> None:
        self._client = client

    def put(self, *, bucket, key, body, media_type, metadata) -> None:
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=media_type,
            Metadata=dict(metadata),
        )


@dataclass(frozen=True)
class PublishedArtifact:
    artifact_id: UUID
    storage_uri: str
    checksum_sha256: str
    size_bytes: int


class SessionIngestionArtifactPublisher:
    artifact_type = "ingestion.manifest"
    media_type = "application/json"

    def __init__(self, session_factory, writer: ArtifactObjectWriter, *, bucket: str) -> None:
        self._session_factory = session_factory
        self._writer = writer
        self._bucket = bucket

    def publish(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        attempt_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        manifest: Mapping[str, Any],
    ) -> PublishedArtifact:
        payload = {
            "contract_version": "ingestion_manifest_v1",
            "organization_id": str(organization_id),
            "execution_id": str(execution_id),
            "attempt_id": str(attempt_id),
            "document_id": str(document_id),
            "document_version_id": str(document_version_id),
            **dict(manifest),
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        checksum = hashlib.sha256(body).hexdigest()
        key = f"{organization_id}/runtime/{execution_id}/ingestion-manifest.json"
        storage_uri = f"s3://{self._bucket}/{key}"

        self._writer.put(
            bucket=self._bucket,
            key=key,
            body=body,
            media_type=self.media_type,
            metadata={
                "sha256": checksum,
                "artifact-type": self.artifact_type,
                "execution-id": str(execution_id),
            },
        )

        session = self._session_factory()
        try:
            artifact = session.scalar(
                select(RuntimeExecutionArtifact).where(
                    RuntimeExecutionArtifact.organization_id == organization_id,
                    RuntimeExecutionArtifact.execution_id == execution_id,
                    RuntimeExecutionArtifact.artifact_type == self.artifact_type,
                    RuntimeExecutionArtifact.storage_uri == storage_uri,
                )
            )
            if artifact is None:
                artifact = RuntimeExecutionArtifact(
                    organization_id=organization_id,
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    artifact_type=self.artifact_type,
                    storage_uri=storage_uri,
                    media_type=self.media_type,
                    checksum_sha256=checksum,
                    size_bytes=len(body),
                    metadata_={
                        "document_id": str(document_id),
                        "document_version_id": str(document_version_id),
                        "contract_version": "ingestion_manifest_v1",
                    },
                    status="published",
                )
                session.add(artifact)
            else:
                artifact.attempt_id = attempt_id
                artifact.checksum_sha256 = checksum
                artifact.size_bytes = len(body)
                artifact.status = "published"
                artifact.metadata_ = {
                    **dict(artifact.metadata_ or {}),
                    "document_id": str(document_id),
                    "document_version_id": str(document_version_id),
                    "contract_version": "ingestion_manifest_v1",
                }
            session.commit()
            return PublishedArtifact(
                artifact_id=artifact.id,
                storage_uri=storage_uri,
                checksum_sha256=checksum,
                size_bytes=len(body),
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
