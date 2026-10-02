import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from app.api.routes.knowledge import retrieve_knowledge
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.schemas.product_api import KnowledgeContextRequest


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _chunk(*, organization_id, document_id, version_id, revision_id, index, key, text):
    return Chunk(
        id=uuid.uuid4(),
        organization_id=organization_id,
        document_record_id=document_id,
        document_version_id=version_id,
        processing_revision_id=revision_id,
        chunk_index=index,
        chunk_key=key,
        content_hash=_hash(text),
        text=text,
        content_type="text/plain",
        section_ref={"section": key},
        provenance={"section": key},
        quality={},
        metadata_json={"content_modality": "text", "evidence_role": "authoritative"},
        status="indexed",
    )


def main():
    now = datetime.now(UTC)
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_ids = (uuid.uuid4(), uuid.uuid4())
    revision_ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    execution_ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    attempt_ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"revision-selection-{uuid.uuid4().hex}",
                name="Revision Selection E2E",
                status="active",
                config={},
            )
        )
        db.flush()
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Revision Selection E2E",
                source_type="e2e",
                source_ref={},
                metadata_json={},
                classification={},
                status="indexed",
            )
        )
        db.flush()
        for number, version_id in enumerate(version_ids, start=1):
            db.add(
                DocumentVersion(
                    id=version_id,
                    organization_id=organization_id,
                    document_record_id=document_id,
                    version_number=number,
                    content_type="text/plain",
                    file_name=f"source-{number}.txt",
                    source_snapshot={},
                    status="indexed",
                )
            )
        db.flush()

        for execution_id in execution_ids:
            db.add(
                RuntimeExecution(
                    id=execution_id,
                    organization_id=organization_id,
                    execution_type="document.ingestion",
                    subject_type="document_version",
                    subject_id=version_ids[0],
                    priority=100,
                    status="pending",
                    input_payload={},
                    policy_snapshot={},
                    metrics={},
                )
            )
        db.flush()
        for execution_id, attempt_id in zip(execution_ids, attempt_ids, strict=False):
            db.add(
                RuntimeExecutionAttempt(
                    id=attempt_id,
                    organization_id=organization_id,
                    execution_id=execution_id,
                    attempt_number=1,
                    status="cancelled",
                    finished_at=now,
                    provider_reference={},
                    metrics={},
                )
            )
        db.flush()

        revision_specs = (
            (revision_ids[0], execution_ids[0], attempt_ids[0], "completed", now - timedelta(minutes=2)),
            (revision_ids[1], execution_ids[1], attempt_ids[1], "completed", now - timedelta(minutes=1)),
            (revision_ids[2], execution_ids[2], attempt_ids[2], "failed", now),
        )
        for revision_id, execution_id, attempt_id, status, completed_at in revision_specs:
            db.add(
                ProcessingRevision(
                    id=revision_id,
                    organization_id=organization_id,
                    document_record_id=document_id,
                    document_version_id=version_ids[0],
                    runtime_execution_id=execution_id,
                    runtime_attempt_id=attempt_id,
                    pipeline_profile_revision="1",
                    adapter_key="platform.text",
                    adapter_version="1.0.0",
                    configuration_snapshot={},
                    status=status,
                    started_at=completed_at - timedelta(seconds=5),
                    completed_at=completed_at,
                    content_unit_count=1,
                    chunk_count=1,
                    created_at=completed_at - timedelta(seconds=5),
                    updated_at=completed_at,
                )
            )
        db.flush()

        db.add_all(
            [
                _chunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_ids[0],
                    revision_id=revision_ids[0],
                    index=0,
                    key="old-completed",
                    text="Revision selection evidence from the older completed revision.",
                ),
                _chunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_ids[0],
                    revision_id=revision_ids[1],
                    index=1,
                    key="latest-completed",
                    text="Revision selection evidence from the latest completed revision.",
                ),
                _chunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_ids[0],
                    revision_id=revision_ids[2],
                    index=2,
                    key="failed-revision",
                    text="Revision selection evidence from a failed revision.",
                ),
                _chunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_ids[1],
                    revision_id=None,
                    index=0,
                    key="legacy-fallback",
                    text="Revision selection evidence from a legacy document version.",
                ),
            ]
        )
        db.commit()

        latest = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="revision selection evidence",
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        explicit = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="revision selection evidence",
                metadata={"processing_revision_id": str(revision_ids[0])},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        failed = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="revision selection evidence",
                metadata={"processing_revision_id": str(revision_ids[2])},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        legacy = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="revision selection evidence",
                metadata={"processing_revision_mode": "legacy_only"},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )

        latest_keys = {item.chunk_key for item in latest.context}
        explicit_keys = {item.chunk_key for item in explicit.context}
        legacy_keys = {item.chunk_key for item in legacy.context}
        latest_citations = {citation.chunk_key: citation.metadata for citation in latest.citations}
        explicit_citations = {citation.chunk_key: citation.metadata for citation in explicit.citations}

        checks = {
            "latest_completed_selected": "latest-completed" in latest_keys,
            "older_completed_excluded_by_default": "old-completed" not in latest_keys,
            "failed_revision_excluded_by_default": "failed-revision" not in latest_keys,
            "legacy_fallback_selected_without_completed_revision": "legacy-fallback" in latest_keys,
            "explicit_completed_selected": explicit_keys == {"old-completed"},
            "explicit_failed_rejected": len(failed.context) == 0,
            "legacy_only_selected": legacy_keys == {"legacy-fallback"},
            "latest_revision_traceable_in_citation": latest_citations["latest-completed"].get("processing_revision_id")
            == str(revision_ids[1]),
            "latest_selection_mode_traceable": latest_citations["latest-completed"].get(
                "processing_revision_selection_mode"
            )
            == "latest_completed",
            "legacy_fallback_traceable": latest_citations["legacy-fallback"].get("processing_revision_selection_mode")
            == "legacy_fallback",
            "explicit_selection_traceable": explicit_citations["old-completed"].get(
                "processing_revision_selection_mode"
            )
            == "explicit",
            "document_versions_isolated": {item.document_version_id for item in latest.context} == set(version_ids),
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "organization_id": str(organization_id),
                    "latest_keys": sorted(latest_keys),
                    "explicit_keys": sorted(explicit_keys),
                    "legacy_keys": sorted(legacy_keys),
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
