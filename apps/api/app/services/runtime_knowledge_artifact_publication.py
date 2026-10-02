from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from sqlalchemy import select

from app.core.config import get_settings
from app.models.documents import Chunk
from app.models.runtime import RuntimeExecutionArtifact
from app.repositories.runtime_artifact_registration import SqlAlchemyRuntimeArtifactRegistry
from app.services.ingestion_artifact_registration import IngestionArtifactRegistrationService
from app.services.knowledge_artifact_publication_flow import KnowledgeArtifactPublicationFlow
from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_artifact_storage import KnowledgeArtifactStorageService
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.s3_artifact_storage import S3ArtifactStorageAdapter
from app.services.s3_visual_record_source import S3VisualRecordSource


class RuntimeKnowledgeArtifactPublicationService:
    """Publishes persisted text and optional visual knowledge records."""

    def __init__(self, session_factory, client: Any | None = None, visual_source=None) -> None:
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
        self._visual_source = visual_source or S3VisualRecordSource(self._client)

    def publish(
        self,
        *,
        organization_id: uuid.UUID,
        execution_id: uuid.UUID,
        attempt_id: uuid.UUID | None,
        document_version_id: uuid.UUID,
        processing_revision_id: uuid.UUID | None,
    ) -> uuid.UUID:
        session = self._session_factory()
        adapter = S3ArtifactStorageAdapter(self._client, bucket_name=self._bucket)
        revision_key = str(processing_revision_id or execution_id)
        try:
            chunks = list(
                session.scalars(
                    select(Chunk)
                    .where(
                        Chunk.organization_id == organization_id,
                        Chunk.document_version_id == document_version_id,
                    )
                    .order_by(Chunk.chunk_index.asc())
                ).all()
            )
            text_records = tuple(_chunk_record(chunk) for chunk in chunks)
            try:
                visual_records = self._visual_source.load(
                    session,
                    organization_id=organization_id,
                    execution_id=execution_id,
                )
                visual_source_failed = False
            except Exception:
                visual_records = ()
                visual_source_failed = True

            composition = KnowledgeNdjsonComposer().compose(
                text_records,
                visual_records=visual_records,
                include_visual=True,
            )
            artifact = KnowledgeArtifactPublisher().build(
                composition,
                document_version_id=str(document_version_id),
                processing_revision_id=revision_key,
                extra_metadata={
                    "organization_id": str(organization_id),
                    "execution_id": str(execution_id),
                    "attempt_id": str(attempt_id) if attempt_id else "",
                    "processing_revision_id": str(processing_revision_id) if processing_revision_id else "",
                    "visual_source_failed": visual_source_failed,
                },
            )
            storage_uri = f"s3://{self._bucket}/{artifact.object_name}"
            checksum = str(artifact.manifest["sha256"])
            runtime_artifact = session.execute(
                select(RuntimeExecutionArtifact).where(
                    RuntimeExecutionArtifact.organization_id == organization_id,
                    RuntimeExecutionArtifact.execution_id == execution_id,
                    RuntimeExecutionArtifact.artifact_type == "knowledge_ndjson",
                    RuntimeExecutionArtifact.storage_uri == storage_uri,
                )
            ).scalar_one_or_none()

            if runtime_artifact is not None:
                if (
                    runtime_artifact.checksum_sha256 != checksum
                    or runtime_artifact.size_bytes != len(artifact.payload)
                    or runtime_artifact.media_type != artifact.content_type
                ):
                    raise RuntimeError("runtime knowledge artifact identity already exists with different content")
                if runtime_artifact.status == "verified":
                    return runtime_artifact.id
            else:
                now = datetime.now(UTC)
                runtime_artifact = RuntimeExecutionArtifact(
                    organization_id=organization_id,
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    artifact_type="knowledge_ndjson",
                    storage_uri=storage_uri,
                    media_type=artifact.content_type,
                    checksum_sha256=checksum,
                    size_bytes=len(artifact.payload),
                    metadata_={
                        "schema": artifact.manifest["schema"],
                        "document_version_id": str(document_version_id),
                        "processing_revision_id": revision_key,
                        "text_record_count": composition.metrics["text_records"],
                        "visual_record_count": composition.metrics["visual_records_included"],
                        "visual_source_failed": visual_source_failed,
                    },
                    status="publishing",
                    created_at=now,
                    updated_at=now,
                )
                session.add(runtime_artifact)
                session.flush()

            registry = SqlAlchemyRuntimeArtifactRegistry(
                session,
                organization_id=organization_id,
                execution_id=execution_id,
                artifact_id=runtime_artifact.id,
                attempt_id=attempt_id,
            )
            flow = KnowledgeArtifactPublicationFlow(
                KnowledgeArtifactStorageService(adapter),
                IngestionArtifactRegistrationService(registry),
            )
            outcome = flow.execute(
                artifact,
                document_version_id=str(document_version_id),
                metadata={"processing_revision_id": revision_key},
            )
            runtime_artifact.status = "verified"
            runtime_artifact.checksum_sha256 = outcome.publication.sha256
            runtime_artifact.size_bytes = outcome.publication.size_bytes
            runtime_artifact.updated_at = datetime.now(UTC)
            session.commit()
            return runtime_artifact.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _chunk_record(chunk: Chunk) -> dict[str, Any]:
    return {
        "schema": "text-knowledge-record/v1",
        "record_id": f"text:{chunk.id}",
        "content": chunk.text,
        "metadata": {
            "content_modality": "text",
            "document_version_id": str(chunk.document_version_id),
            "chunk_id": str(chunk.id),
            "chunk_key": chunk.chunk_key,
            "chunk_index": chunk.chunk_index,
            "content_hash": chunk.content_hash,
            "section_ref": dict(chunk.section_ref or {}),
            "provenance": dict(chunk.provenance or {}),
            "quality": dict(chunk.quality or {}),
            "metadata": dict(chunk.metadata_json or {}),
        },
    }
