import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.documents import Chunk, DocumentRecord, DocumentVersion, IndexingJob
from app.schemas.product_api import IndexingJobCreateRequest, IndexingJobRead, IndexingJobRunRequest, ProductApiStatus

router = APIRouter(prefix="/indexing", tags=["indexing"])

SUPPORTED_INDEX_TARGETS = {"postgres_fts", "vector_derived"}


def _now() -> datetime:
    return datetime.now(UTC)


def _merge_metrics(existing: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(existing or {})
    value.update(patch or {})
    return value


def _index_lifecycle_metrics(
    index_target: str, *, vector_provider: str | None = None, vector_collection_name: str | None = None
) -> dict[str, Any]:
    if index_target == "vector_derived":
        return {
            "indexing_contract": "derived_vector_index_lifecycle_v1",
            "index_target": index_target,
            "index_source_of_truth": "postgresql_chunks",
            "vector_index_lifecycle_enabled": True,
            "vector_index_derived": True,
            "vector_index_rebuildable": True,
            "vector_index_persisted": False,
            "vector_index_status": "pending",
            "vector_provider_ref": vector_provider,
            "vector_collection_name": vector_collection_name,
            "embedding_generated": False,
            "vector_indexed": False,
            "llm_used": False,
        }
    return {
        "indexing_contract": "indexing_execution_v1",
        "index_target": index_target,
        "index_source_of_truth": "postgresql_chunks",
        "vector_index_lifecycle_enabled": False,
        "embedding_generated": False,
        "vector_indexed": False,
        "llm_used": False,
    }


def _read_job(job: IndexingJob) -> IndexingJobRead:
    return IndexingJobRead(
        id=job.id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        organization_id=job.organization_id,
        collection_id=job.collection_id,
        document_record_id=job.document_record_id,
        document_version_id=job.document_version_id,
        ingestion_job_id=job.ingestion_job_id,
        index_target=job.index_target,
        embedding_model_id=job.embedding_model_id,
        vector_provider=job.vector_provider,
        vector_collection_name=job.vector_collection_name,
        status=job.status,
        attempt_count=job.attempt_count,
        started_at=job.started_at,
        finished_at=job.finished_at,
        indexed_chunk_count=job.indexed_chunk_count,
        failed_chunk_count=job.failed_chunk_count,
        metrics=job.metrics or {},
        error_code=job.error_code,
        error_message=job.error_message,
    )


def _chunk_query(db: Session, job: IndexingJob):
    query = db.query(Chunk).filter(Chunk.organization_id == job.organization_id)
    if job.collection_id is not None:
        query = query.filter(Chunk.collection_id == job.collection_id)
    if job.document_record_id is not None:
        query = query.filter(Chunk.document_record_id == job.document_record_id)
    if job.document_version_id is not None:
        query = query.filter(Chunk.document_version_id == job.document_version_id)
    return query


@router.get("/status", response_model=ProductApiStatus)
def indexing_status():
    return ProductApiStatus()


@router.post("/jobs", response_model=IndexingJobRead, status_code=status.HTTP_201_CREATED)
def create_indexing_job(payload: IndexingJobCreateRequest, db: Session = Depends(get_db)):
    if payload.index_target not in SUPPORTED_INDEX_TARGETS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported index target")

    if payload.document_version_id is not None:
        document_version = db.get(DocumentVersion, payload.document_version_id)
        if document_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document version not found")
        if document_version.organization_id != payload.organization_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="document version does not belong to organization"
            )
        if payload.document_record_id is None:
            payload.document_record_id = document_version.document_record_id

    if payload.document_record_id is not None:
        document_record = db.get(DocumentRecord, payload.document_record_id)
        if document_record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document record not found")
        if document_record.organization_id != payload.organization_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="document record does not belong to organization"
            )

    job = IndexingJob(
        organization_id=payload.organization_id,
        collection_id=payload.collection_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
        ingestion_job_id=payload.ingestion_job_id,
        index_target=payload.index_target,
        embedding_model_id=payload.embedding_model_id,
        vector_provider=payload.vector_provider,
        vector_collection_name=payload.vector_collection_name,
        status="pending",
        attempt_count=0,
        indexed_chunk_count=0,
        failed_chunk_count=0,
        metrics=_merge_metrics(
            payload.metrics,
            _index_lifecycle_metrics(
                payload.index_target,
                vector_provider=payload.vector_provider,
                vector_collection_name=payload.vector_collection_name,
            ),
        ),
    )

    try:
        db.add(job)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="indexing job violates a database constraint"
        ) from exc

    db.refresh(job)
    return _read_job(job)


@router.get("/jobs", response_model=list[IndexingJobRead])
def list_indexing_jobs(
    organization_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = 0,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(IndexingJob).filter(IndexingJob.organization_id == organization_id)
    if status_filter is not None:
        query = query.filter(IndexingJob.status == status_filter)
    jobs = query.order_by(IndexingJob.created_at.desc()).offset(skip).limit(limit).all()
    return [_read_job(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=IndexingJobRead)
def get_indexing_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(IndexingJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="indexing job not found")
    return _read_job(job)


def _run_postgres_fts_job(job: IndexingJob, chunks: list[Chunk], db: Session) -> tuple[int, int, dict[str, Any]]:
    indexed_count = 0
    failed_count = 0
    for chunk in chunks:
        db.execute(
            sql_text(
                "update documents.chunks "
                "set fts_vector = to_tsvector('simple', coalesce(text, '')), status = 'indexed' "
                "where id = :chunk_id"
            ),
            {"chunk_id": str(chunk.id)},
        )
        indexed_count += 1
    return (
        indexed_count,
        failed_count,
        {
            "fts_vector_populated": True,
            "embedding_generated": False,
            "vector_indexed": False,
            "llm_used": False,
        },
    )


def _run_vector_derived_job(job: IndexingJob, chunks: list[Chunk]) -> tuple[int, int, dict[str, Any]]:
    source_chunk_count = len(chunks)
    return (
        source_chunk_count,
        0,
        {
            "fts_vector_populated": False,
            "embedding_generated": False,
            "embedding_execution_enabled": False,
            "embedding_status": "not_executed",
            "vector_index_lifecycle_enabled": True,
            "vector_index_derived": True,
            "vector_index_rebuildable": True,
            "vector_index_persisted": False,
            "vector_index_status": "ready_reference_only",
            "vector_index_source_chunk_count": source_chunk_count,
            "vector_index_write_enabled": False,
            "vector_index_rebuild_strategy": "rebuild_from_postgresql_chunks",
            "vector_provider_ref": job.vector_provider,
            "vector_collection_name": job.vector_collection_name,
            "vector_indexed": False,
            "llm_used": False,
        },
    )


@router.post("/jobs/{job_id}/run", response_model=IndexingJobRead)
def run_indexing_job(job_id: uuid.UUID, payload: IndexingJobRunRequest, db: Session = Depends(get_db)):
    job = db.get(IndexingJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="indexing job not found")
    if job.index_target not in SUPPORTED_INDEX_TARGETS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported index target")
    if job.status == "succeeded" and not payload.force:
        return _read_job(job)

    started_at = _now()
    job.status = "running"
    job.started_at = started_at
    job.finished_at = None
    job.attempt_count += 1
    job.metrics = _merge_metrics(job.metrics, {**payload.metrics, "started_at": started_at.isoformat()})
    db.commit()
    db.refresh(job)

    chunks = _chunk_query(db, job).order_by(Chunk.chunk_index.asc()).all()

    try:
        if job.index_target == "vector_derived":
            indexed_count, failed_count, execution_metrics = _run_vector_derived_job(job, chunks)
        else:
            indexed_count, failed_count, execution_metrics = _run_postgres_fts_job(job, chunks, db)

        finished_at = _now()
        job.status = "succeeded"
        job.finished_at = finished_at
        job.indexed_chunk_count = indexed_count
        job.failed_chunk_count = failed_count
        job.error_code = None
        job.error_message = None
        job.metrics = _merge_metrics(
            job.metrics,
            {
                "finished_at": finished_at.isoformat(),
                "index_target": job.index_target,
                "indexed_chunk_count": indexed_count,
                "failed_chunk_count": failed_count,
                **execution_metrics,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_at = _now()
        job = db.get(IndexingJob, job_id)
        if job is not None:
            job.status = "failed"
            job.finished_at = failed_at
            job.failed_chunk_count = 1
            job.error_code = "indexing_execution_failed"
            job.error_message = str(exc)
            job.metrics = _merge_metrics(job.metrics, {"failed_at": failed_at.isoformat()})
            db.commit()
            db.refresh(job)
            return _read_job(job)
        raise

    db.refresh(job)
    return _read_job(job)
