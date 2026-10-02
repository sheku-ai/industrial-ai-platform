import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.documents import DocumentRecord, DocumentVersion, IngestionJob
from app.schemas.product_api import (
    IngestionJobClaimRequest,
    IngestionJobTransitionRequest,
    IngestionUploadRequest,
    IngestionUploadResponse,
    ProductApiStatus,
)
from app.schemas.runtime import IngestionJobRead

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

CLAIMABLE_JOB_STATUSES = {"pending", "queued"}
ACTIVE_JOB_STATUSES = {"claimed", "running"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
VALID_JOB_STATUSES = CLAIMABLE_JOB_STATUSES | ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES


def _now() -> datetime:
    return datetime.now(UTC)


def _source_ref(payload: IngestionUploadRequest) -> dict[str, Any]:
    value = dict(payload.source_ref or {})
    object_ref = {
        key: val
        for key, val in {
            "provider": payload.object_store_provider,
            "bucket": payload.object_store_bucket,
            "key": payload.object_store_key,
        }.items()
        if val is not None
    }
    if object_ref and "object_store" not in value:
        value["object_store"] = object_ref
    return value


def _source_snapshot(payload: IngestionUploadRequest, source_ref: dict[str, Any]) -> dict[str, Any]:
    value = dict(payload.source_snapshot or {})
    value.setdefault("source_type", payload.source_type)
    value.setdefault("source_ref", source_ref)
    value.setdefault("registration_contract", "ingestion_registration_v1")
    value.setdefault("registration_only", True)
    return value


def _merge_metrics(existing: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(existing or {})
    value.update(patch or {})
    return value


def _ensure_status(value: str) -> str:
    if value not in VALID_JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unsupported ingestion job status: {value}"
        )
    return value


@router.get("/status", response_model=ProductApiStatus)
def ingestion_status():
    return ProductApiStatus()


@router.post("/register", response_model=IngestionUploadResponse, status_code=status.HTTP_201_CREATED)
def register_ingestion_request(payload: IngestionUploadRequest, db: Session = Depends(get_db)):
    source_ref = _source_ref(payload)
    source_snapshot = _source_snapshot(payload, source_ref)

    document_record = DocumentRecord(
        organization_id=payload.organization_id,
        collection_id=payload.collection_id,
        document_type_id=payload.document_type_id,
        metadata_template_id=payload.metadata_template_id,
        external_reference=payload.external_reference,
        title=payload.title,
        description=payload.description,
        source_type=payload.source_type,
        source_ref=source_ref,
        metadata_json=payload.metadata,
        classification=payload.classification,
        status="registered",
    )

    try:
        db.add(document_record)
        db.flush()

        document_version = DocumentVersion(
            organization_id=payload.organization_id,
            document_record_id=document_record.id,
            version_number=1,
            version_label=payload.version_label,
            content_type=payload.content_type,
            file_name=payload.file_name,
            size_bytes=payload.size_bytes,
            checksum_sha256=payload.checksum_sha256,
            object_store_provider=payload.object_store_provider,
            object_store_bucket=payload.object_store_bucket,
            object_store_key=payload.object_store_key,
            source_snapshot=source_snapshot,
            status="registered",
        )
        db.add(document_version)
        db.flush()

        ingestion_job = IngestionJob(
            organization_id=payload.organization_id,
            document_record_id=document_record.id,
            document_version_id=document_version.id,
            requested_by=payload.requested_by,
            job_type="ingestion",
            pipeline_name=payload.pipeline_name,
            pipeline_version=payload.pipeline_version,
            adapter_profile=payload.adapter_profile,
            chunking_profile=payload.chunking_profile,
            quality_profile=payload.quality_profile,
            publication_profile=payload.publication_profile,
            status="pending",
            priority=payload.priority,
            attempt_count=0,
            max_attempts=payload.max_attempts,
            metrics={"registration_only": True, "execution_started": False},
        )
        db.add(ingestion_job)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="ingestion registration violates a persistence constraint"
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(document_record)
    db.refresh(document_version)
    db.refresh(ingestion_job)

    return IngestionUploadResponse(
        document_record_id=document_record.id,
        document_version_id=document_version.id,
        ingestion_job_id=ingestion_job.id,
        status="registered",
        document_status=document_record.status,
        version_status=document_version.status,
        job_status=ingestion_job.status,
    )


@router.get("/jobs", response_model=list[IngestionJobRead])
def list_ingestion_jobs(
    skip: int = 0,
    limit: int = 100,
    organization_id: uuid.UUID | None = None,
    job_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(IngestionJob)
    if organization_id is not None:
        query = query.filter(IngestionJob.organization_id == organization_id)
    if job_status is not None:
        query = query.filter(IngestionJob.status == _ensure_status(job_status))
    return query.order_by(IngestionJob.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=IngestionJobRead)
def get_ingestion_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingestion job not found")
    return job


@router.post("/jobs/claim", response_model=IngestionJobRead)
def claim_next_ingestion_job(payload: IngestionJobClaimRequest, db: Session = Depends(get_db)):
    query = db.query(IngestionJob).filter(
        IngestionJob.status.in_(tuple(CLAIMABLE_JOB_STATUSES)),
        IngestionJob.attempt_count < IngestionJob.max_attempts,
    )
    if payload.organization_id is not None:
        query = query.filter(IngestionJob.organization_id == payload.organization_id)
    if payload.job_type is not None:
        query = query.filter(IngestionJob.job_type == payload.job_type)

    job = (
        query.order_by(IngestionJob.priority.asc(), IngestionJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no claimable ingestion job found")

    now = _now()
    job.status = "claimed"
    job.locked_by = payload.worker_id
    job.locked_at = now
    job.attempt_count += 1
    job.metrics = _merge_metrics(
        job.metrics,
        {"claimed_by": payload.worker_id, "claimed_at": now.isoformat(), "execution_started": False},
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/transition", response_model=IngestionJobRead)
def transition_ingestion_job(job_id: uuid.UUID, payload: IngestionJobTransitionRequest, db: Session = Depends(get_db)):
    job = db.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingestion job not found")

    target_status = _ensure_status(payload.status)
    now = _now()

    if target_status == "running":
        job.started_at = job.started_at or now
    if target_status in TERMINAL_JOB_STATUSES:
        job.finished_at = now
    if target_status in {"pending", "queued"}:
        job.locked_by = None
        job.locked_at = None
    elif payload.worker_id is not None:
        job.locked_by = payload.worker_id
        job.locked_at = job.locked_at or now

    job.status = target_status
    job.error_code = payload.error_code
    job.error_message = payload.error_message
    job.metrics = _merge_metrics(
        job.metrics,
        {
            **payload.metrics,
            "last_transition_status": target_status,
            "last_transition_at": now.isoformat(),
            "execution_started": target_status in {"running", "succeeded", "failed"},
        },
    )

    db.commit()
    db.refresh(job)
    return job
