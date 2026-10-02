import hashlib

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.core import Organization
from app.models.documents import Chunk, Collection, DocumentRecord, DocumentVersion, IndexingJob, IngestionJob

router = APIRouter(prefix="/smoke", tags=["smoke"])


@router.post("/knowledge-runtime/seed")
def seed_knowledge_runtime(db: Session = Depends(get_db)):
    organization = db.query(Organization).filter(Organization.slug == "smoke-org").first()
    if organization is None:
        organization = Organization(
            slug="smoke-org",
            name="Smoke Test Organization",
            description="Generic organization used only for Knowledge Runtime smoke validation.",
            status="active",
            config={"scope": "smoke"},
        )
        db.add(organization)
        db.flush()

    collection = (
        db.query(Collection)
        .filter(Collection.organization_id == organization.id, Collection.code == "smoke-knowledge")
        .first()
    )
    if collection is None:
        collection = Collection(
            organization_id=organization.id,
            code="smoke-knowledge",
            name="Smoke Knowledge Collection",
            description="Generic collection used for Knowledge Runtime smoke validation.",
            vector_provider="none",
            vector_collection_name="smoke_knowledge",
            config={"scope": "smoke"},
            status="active",
        )
        db.add(collection)
        db.flush()

    document = (
        db.query(DocumentRecord)
        .filter(
            DocumentRecord.organization_id == organization.id, DocumentRecord.external_reference == "smoke-document"
        )
        .first()
    )
    if document is None:
        document = DocumentRecord(
            organization_id=organization.id,
            collection_id=collection.id,
            external_reference="smoke-document",
            title="Generic Smoke Knowledge Document",
            description="Generic smoke document for validating persisted chunks, context and citations.",
            source_type="smoke",
            source_ref={"provider": "smoke", "reference": "smoke-document"},
            metadata_json={"scope": "smoke"},
            classification={"level": "internal"},
            status="registered",
        )
        db.add(document)
        db.flush()

    version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_record_id == document.id, DocumentVersion.version_number == 1)
        .first()
    )
    if version is None:
        version = DocumentVersion(
            organization_id=organization.id,
            document_record_id=document.id,
            version_number=1,
            version_label="smoke-v1",
            content_type="text/plain",
            file_name="smoke-knowledge.txt",
            size_bytes=512,
            checksum_sha256="smoke",
            object_store_provider="none",
            object_store_bucket="smoke",
            object_store_key="smoke/smoke-knowledge.txt",
            source_snapshot={"scope": "smoke"},
            status="registered",
        )
        db.add(version)
        db.flush()

    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.organization_id == organization.id, IngestionJob.document_version_id == version.id)
        .first()
    )
    if job is None:
        job = IngestionJob(
            organization_id=organization.id,
            document_record_id=document.id,
            document_version_id=version.id,
            requested_by="smoke",
            job_type="ingestion",
            pipeline_name="smoke_ingestion",
            adapter_profile={"adapter_name": "smoke"},
            chunking_profile={"strategy": "fixed"},
            quality_profile={"strategy": "accept"},
            publication_profile={"provider": "none"},
            status="succeeded",
            priority=100,
            attempt_count=1,
            max_attempts=3,
            metrics={"scope": "smoke"},
        )
        db.add(job)
        db.flush()

    texts = [
        "The Industrial AI Platform stores platform configuration and runtime state in PostgreSQL "
        "as the system of record.",
        "Object storage is used for artifacts only and must not become the source of truth for product records.",
        "Retrieval orchestration combines lexical results, vector results, hybrid merge, context assembly "
        "and deterministic citations.",
    ]
    created_chunks = 0
    for index, text in enumerate(texts):
        existing = db.query(Chunk).filter(Chunk.document_version_id == version.id, Chunk.chunk_index == index).first()
        if existing is not None:
            continue
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk = Chunk(
            organization_id=organization.id,
            document_record_id=document.id,
            document_version_id=version.id,
            collection_id=collection.id,
            chunk_index=index,
            chunk_key=f"smoke:{index}",
            content_hash=content_hash,
            semantic_hash=None,
            text=text,
            content_type="text/plain",
            section_ref={"section": "smoke"},
            provenance={"source": "smoke"},
            quality={"accepted": True},
            metadata_json={"scope": "smoke", "index": index},
            status="created",
        )
        db.add(chunk)
        created_chunks += 1

    indexing_job = (
        db.query(IndexingJob)
        .filter(IndexingJob.organization_id == organization.id, IndexingJob.document_version_id == version.id)
        .first()
    )
    if indexing_job is None:
        indexing_job = IndexingJob(
            organization_id=organization.id,
            collection_id=collection.id,
            document_record_id=document.id,
            document_version_id=version.id,
            ingestion_job_id=job.id,
            index_target="lexical_postgres",
            vector_provider="none",
            vector_collection_name="smoke_knowledge",
            status="succeeded",
            attempt_count=1,
            indexed_chunk_count=len(texts),
            failed_chunk_count=0,
            metrics={"scope": "smoke"},
        )
        db.add(indexing_job)

    db.commit()

    return {
        "status": "seeded",
        "organization_id": str(organization.id),
        "collection_id": str(collection.id),
        "document_record_id": str(document.id),
        "document_version_id": str(version.id),
        "ingestion_job_id": str(job.id),
        "created_chunks": created_chunks,
        "total_chunks": len(texts),
    }
