import hashlib
import json
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


def main():
    now = datetime.now(UTC)
    organization_id, document_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    execution_ids = (uuid.uuid4(), uuid.uuid4())
    attempt_ids = (uuid.uuid4(), uuid.uuid4())
    revision_ids = (uuid.uuid4(), uuid.uuid4())
    text = "Authoritative source text remains independently searchable."
    visual = VisualKnowledgeRecord(
        record_id="visual:image-revision-e2e",
        content="Visual content: generic diagram with two connected components.",
        metadata={
            "content_modality": "visual_description",
            "evidence_role": "derived",
            "citation_basis": "derived_visual_description",
            "derived_content": True,
            "image_hash": "image-revision-e2e",
            "source_locator": {"page_number": 1},
            "provider_key": "deterministic-local-vision",
            "visual_status": "succeeded",
        },
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"visual-revision-{uuid.uuid4().hex}",
                name="Visual Revision E2E",
                status="active",
                config={},
            )
        )
        db.flush()
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Visual Revision E2E",
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

        for execution_id in execution_ids:
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
        for execution_id, attempt_id, revision_id in zip(execution_ids, attempt_ids, revision_ids, strict=False):
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

        text_chunk = Chunk(
            id=uuid.uuid4(),
            organization_id=organization_id,
            document_record_id=document_id,
            document_version_id=version_id,
            processing_revision_id=revision_ids[0],
            chunk_index=0,
            chunk_key="text:0",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            text=text,
            content_type="text/plain",
            section_ref={"page_number": 1},
            provenance={"page_number": 1},
            quality={},
            metadata_json={"content_modality": "text", "evidence_role": "authoritative"},
            status="indexed",
        )
        db.add(text_chunk)
        db.flush()

        materializer = VisualKnowledgeChunkMaterializer()
        first = materializer.materialize(
            db,
            organization_id=organization_id,
            document_version_id=version_id,
            processing_revision_id=revision_ids[0],
            text_chunks=(text_chunk,),
            visual_records=(visual,),
        )
        second = materializer.materialize(
            db,
            organization_id=organization_id,
            document_version_id=version_id,
            processing_revision_id=revision_ids[0],
            text_chunks=(text_chunk,),
            visual_records=(visual,),
        )
        third = materializer.materialize(
            db,
            organization_id=organization_id,
            document_version_id=version_id,
            processing_revision_id=revision_ids[1],
            text_chunks=(text_chunk,),
            visual_records=(visual,),
        )
        db.commit()

        visual_chunks = tuple(
            db.scalars(
                select(Chunk)
                .where(
                    Chunk.document_version_id == version_id,
                    Chunk.metadata_json["content_modality"].astext == "visual_description",
                )
                .order_by(Chunk.chunk_index.asc())
            ).all()
        )
        counts_by_revision = {
            str(revision_id): sum(1 for chunk in visual_chunks if chunk.processing_revision_id == revision_id)
            for revision_id in revision_ids
        }
        indexes = [chunk.chunk_index for chunk in visual_chunks]
        checks = {
            "first_publication_created": first.created == 1 and first.existing == 0,
            "same_revision_idempotent": second.created == 0 and second.existing == 1,
            "new_revision_created": third.created == 1 and third.existing == 0,
            "one_visual_per_revision": all(value == 1 for value in counts_by_revision.values()),
            "two_revision_records_retained": len(visual_chunks) == 2,
            "chunk_indexes_unique": len(indexes) == len(set(indexes)),
            "stable_visual_identity": all(chunk.chunk_key == "visual:image-revision-e2e" for chunk in visual_chunks),
            "derived_metadata_preserved": all(
                (chunk.metadata_json or {}).get("evidence_role") == "derived" for chunk in visual_chunks
            ),
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "document_version_id": str(version_id),
                    "revision_ids": [str(value) for value in revision_ids],
                    "visual_chunk_count": len(visual_chunks),
                    "counts_by_revision": counts_by_revision,
                    "chunk_indexes": indexes,
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
