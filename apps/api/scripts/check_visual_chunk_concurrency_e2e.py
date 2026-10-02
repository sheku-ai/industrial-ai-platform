import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.services.visual_knowledge_chunk_materializer import VisualKnowledgeChunkMaterializer
from app.services.visual_knowledge_records import VisualKnowledgeRecord


def _materialize_concurrently(
    *,
    barrier,
    outcomes,
    outcome_lock,
    organization_id,
    version_id,
    text_chunk_id,
    processing_revision_id,
    visual,
):
    db = SessionLocal()
    try:
        text_chunk = db.get(Chunk, text_chunk_id)
        barrier.wait(timeout=10)
        result = VisualKnowledgeChunkMaterializer().materialize(
            db,
            organization_id=organization_id,
            document_version_id=version_id,
            processing_revision_id=processing_revision_id,
            text_chunks=(text_chunk,),
            visual_records=(visual,),
        )
        db.commit()
        outcome = {"created": result.created, "existing": result.existing, "error": None}
    except Exception as exc:
        db.rollback()
        outcome = {"created": 0, "existing": 0, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        db.close()

    with outcome_lock:
        outcomes.append(outcome)


def _run_race(
    *,
    organization_id,
    version_id,
    text_chunk_id,
    processing_revision_id,
    visual,
):
    barrier = threading.Barrier(2)
    outcomes = []
    outcome_lock = threading.Lock()
    threads = [
        threading.Thread(
            target=_materialize_concurrently,
            kwargs={
                "barrier": barrier,
                "outcomes": outcomes,
                "outcome_lock": outcome_lock,
                "organization_id": organization_id,
                "version_id": version_id,
                "text_chunk_id": text_chunk_id,
                "processing_revision_id": processing_revision_id,
                "visual": visual,
            },
            daemon=True,
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return outcomes, all(not thread.is_alive() for thread in threads)


def main():
    now = datetime.now(UTC)
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    text_chunk_id = uuid.uuid4()
    text_content = "Authoritative source text for PostgreSQL concurrency validation."

    revision_visual = VisualKnowledgeRecord(
        record_id="visual:concurrency-revision",
        content="Visual content: concurrency-safe derived description for one processing revision.",
        metadata={
            "content_modality": "visual_description",
            "evidence_role": "derived",
            "citation_basis": "derived_visual_description",
            "derived_content": True,
            "image_hash": "concurrency-revision-image",
            "source_locator": {"page_number": 1},
            "provider_key": "deterministic-local-vision",
            "visual_status": "succeeded",
        },
    )
    legacy_visual = VisualKnowledgeRecord(
        record_id="visual:concurrency-null-revision",
        content="Visual content: concurrency-safe derived description without a processing revision.",
        metadata={
            "content_modality": "visual_description",
            "evidence_role": "derived",
            "citation_basis": "derived_visual_description",
            "derived_content": True,
            "image_hash": "concurrency-null-revision-image",
            "source_locator": {"page_number": 2},
            "provider_key": "deterministic-local-vision",
            "visual_status": "succeeded",
        },
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"visual-concurrency-{uuid.uuid4().hex}",
                name="Visual Concurrency E2E",
                status="active",
                config={},
            )
        )
        db.flush()
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Visual Concurrency E2E",
                source_type="e2e",
                source_ref={},
                metadata_json={},
                classification={},
                status="indexed",
            )
        )
        db.flush()
        db.add(
            DocumentVersion(
                id=version_id,
                organization_id=organization_id,
                document_record_id=document_id,
                version_number=1,
                content_type="application/pdf",
                file_name="source.pdf",
                source_snapshot={},
                status="indexed",
            )
        )
        db.flush()
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=organization_id,
                execution_type="document.ingestion",
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="pending",
                input_payload={},
                policy_snapshot={},
                metrics={},
            )
        )
        db.flush()
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
        db.add(
            ProcessingRevision(
                id=revision_id,
                organization_id=organization_id,
                document_record_id=document_id,
                document_version_id=version_id,
                runtime_execution_id=execution_id,
                runtime_attempt_id=attempt_id,
                pipeline_profile_revision="1",
                adapter_key="platform.pdf.text_layer",
                adapter_version="1.0.0",
                configuration_snapshot={},
                status="completed",
                started_at=now,
                completed_at=now,
                content_unit_count=1,
                chunk_count=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            Chunk(
                id=text_chunk_id,
                organization_id=organization_id,
                document_record_id=document_id,
                document_version_id=version_id,
                processing_revision_id=revision_id,
                chunk_index=0,
                chunk_key="text:0",
                content_hash=hashlib.sha256(text_content.encode()).hexdigest(),
                text=text_content,
                content_type="text/plain",
                section_ref={"page_number": 1},
                provenance={"page_number": 1},
                quality={},
                metadata_json={"content_modality": "text", "evidence_role": "authoritative"},
                status="indexed",
            )
        )
        db.commit()
    finally:
        db.close()

    revision_outcomes, revision_threads_finished = _run_race(
        organization_id=organization_id,
        version_id=version_id,
        text_chunk_id=text_chunk_id,
        processing_revision_id=revision_id,
        visual=revision_visual,
    )
    null_revision_outcomes, null_revision_threads_finished = _run_race(
        organization_id=organization_id,
        version_id=version_id,
        text_chunk_id=text_chunk_id,
        processing_revision_id=None,
        visual=legacy_visual,
    )

    db = SessionLocal()
    try:
        visual_chunks = tuple(
            db.scalars(
                select(Chunk)
                .where(
                    Chunk.organization_id == organization_id,
                    Chunk.document_version_id == version_id,
                    Chunk.metadata_json["content_modality"].astext == "visual_description",
                )
                .order_by(Chunk.chunk_index.asc())
            ).all()
        )
    finally:
        db.close()

    revision_chunks = [
        chunk
        for chunk in visual_chunks
        if chunk.processing_revision_id == revision_id and chunk.chunk_key == "visual:concurrency-revision-image"
    ]
    null_revision_chunks = [
        chunk
        for chunk in visual_chunks
        if chunk.processing_revision_id is None and chunk.chunk_key == "visual:concurrency-null-revision-image"
    ]
    chunk_indexes = [chunk.chunk_index for chunk in visual_chunks]

    def _outcomes_are_idempotent(outcomes):
        return (
            len(outcomes) == 2
            and all(outcome["error"] is None for outcome in outcomes)
            and sorted((outcome["created"], outcome["existing"]) for outcome in outcomes) == [(0, 1), (1, 0)]
        )

    checks = {
        "revision_threads_finished": revision_threads_finished,
        "null_revision_threads_finished": null_revision_threads_finished,
        "revision_race_idempotent": _outcomes_are_idempotent(revision_outcomes),
        "null_revision_race_idempotent": _outcomes_are_idempotent(null_revision_outcomes),
        "one_chunk_for_revision_race": len(revision_chunks) == 1,
        "one_chunk_for_null_revision_race": len(null_revision_chunks) == 1,
        "chunk_indexes_unique": len(chunk_indexes) == len(set(chunk_indexes)),
        "no_concurrency_errors": all(
            outcome["error"] is None for outcome in revision_outcomes + null_revision_outcomes
        ),
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "organization_id": str(organization_id),
                "document_version_id": str(version_id),
                "processing_revision_id": str(revision_id),
                "revision_outcomes": revision_outcomes,
                "null_revision_outcomes": null_revision_outcomes,
                "visual_chunk_count": len(visual_chunks),
                "chunk_indexes": chunk_indexes,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
