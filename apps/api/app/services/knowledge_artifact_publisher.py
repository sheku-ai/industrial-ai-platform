from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.knowledge_ndjson_composer import KnowledgeArtifactComposition

KNOWLEDGE_ARTIFACT_SCHEMA = "knowledge-artifact-manifest/v1"


@dataclass(frozen=True)
class PublishableKnowledgeArtifact:
    payload: bytes
    manifest: Mapping[str, Any]
    object_name: str
    content_type: str = "application/x-ndjson"


class KnowledgeArtifactPublisher:
    def build(
        self,
        composition: KnowledgeArtifactComposition,
        *,
        document_version_id: str,
        artifact_name: str = "knowledge.ndjson",
        processing_revision_id: str | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> PublishableKnowledgeArtifact:
        document_version_id = document_version_id.strip()
        artifact_name = artifact_name.strip()
        processing_revision_id = processing_revision_id.strip() if processing_revision_id is not None else None
        if not document_version_id:
            raise ValueError("document_version_id is required")
        if not artifact_name or artifact_name != artifact_name.split("/")[-1]:
            raise ValueError("artifact_name must be a plain file name")
        if processing_revision_id == "":
            raise ValueError("processing_revision_id must be non-blank when provided")
        if processing_revision_id and "/" in processing_revision_id:
            raise ValueError("processing_revision_id must be a path-safe identifier")

        payload = composition.ndjson.encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
        if processing_revision_id:
            object_name = f"document-versions/{document_version_id}/revisions/{processing_revision_id}/{artifact_name}"
        else:
            object_name = f"document-versions/{document_version_id}/{artifact_name}"
        manifest = {
            "schema": KNOWLEDGE_ARTIFACT_SCHEMA,
            "document_version_id": document_version_id,
            "processing_revision_id": processing_revision_id,
            "artifact_name": artifact_name,
            "object_name": object_name,
            "content_type": "application/x-ndjson",
            "encoding": "utf-8",
            "size_bytes": len(payload),
            "sha256": checksum,
            "record_count": composition.metrics.get("total_records", len(composition.records)),
            "text_record_count": composition.metrics.get("text_records", 0),
            "visual_record_count": composition.metrics.get("visual_records_included", 0),
            "visual_records_available": composition.metrics.get("visual_records_available", 0),
            "metadata": dict(extra_metadata or {}),
        }
        return PublishableKnowledgeArtifact(
            payload=payload,
            manifest=manifest,
            object_name=object_name,
        )

    @staticmethod
    def manifest_json(artifact: PublishableKnowledgeArtifact) -> str:
        return json.dumps(artifact.manifest, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def verify(artifact: PublishableKnowledgeArtifact) -> bool:
        return (
            artifact.manifest.get("sha256") == hashlib.sha256(artifact.payload).hexdigest()
            and artifact.manifest.get("size_bytes") == len(artifact.payload)
            and artifact.manifest.get("object_name") == artifact.object_name
        )
