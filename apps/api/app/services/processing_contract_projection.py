from __future__ import annotations

from app.contracts.processing import ProcessingEvidenceV1
from app.models.processing import ProcessingRevision


def project_processing_evidence_v1(revision: ProcessingRevision) -> ProcessingEvidenceV1:
    """Project persisted processing evidence into the canonical v1 contract.

    ``ProcessingRevision`` remains the authoritative PostgreSQL record. This
    function performs a deterministic read projection and does not derive or
    persist additional completion state.
    """

    return ProcessingEvidenceV1(
        evidence_id=revision.id,
        organization_id=revision.organization_id,
        document_record_id=revision.document_record_id,
        document_version_id=revision.document_version_id,
        runtime_execution_id=revision.runtime_execution_id,
        runtime_attempt_id=revision.runtime_attempt_id,
        pipeline_profile_id=revision.pipeline_profile_id,
        pipeline_profile_revision=revision.pipeline_profile_revision,
        adapter_key=revision.adapter_key,
        adapter_version=revision.adapter_version,
        status=revision.status,
        started_at=revision.started_at,
        completed_at=revision.completed_at,
        source_checksum_sha256=revision.source_checksum_sha256,
        content_unit_count=revision.content_unit_count,
        chunk_count=revision.chunk_count,
        manifest_artifact_id=revision.manifest_artifact_id,
        configuration_snapshot=dict(revision.configuration_snapshot or {}),
    )
