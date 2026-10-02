"""Controlled Document Management registration execution service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.documents import DocumentRecord
from app.schemas.documents import DocumentRegistrationRequest
from app.services.document_registration import build_document_registration_plan

DOCUMENT_REGISTRATION_EXECUTION_SCHEMA_VERSION = "1"


def _issue(code: str, message: str, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _read_record(record: DocumentRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "organization_id": str(record.organization_id),
        "collection_id": str(record.collection_id) if record.collection_id else None,
        "document_type_id": str(record.document_type_id) if record.document_type_id else None,
        "metadata_template_id": str(record.metadata_template_id) if record.metadata_template_id else None,
        "external_reference": record.external_reference,
        "title": record.title,
        "description": record.description,
        "source_type": record.source_type,
        "source_ref": record.source_ref or {},
        "metadata": record.metadata_json or {},
        "classification": record.classification or {},
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def _existing_record(db: Session, organization_id: uuid.UUID, external_reference: str | None) -> DocumentRecord | None:
    if not external_reference:
        return None
    statement = (
        select(DocumentRecord)
        .where(DocumentRecord.organization_id == organization_id)
        .where(DocumentRecord.external_reference == external_reference)
        .order_by(DocumentRecord.id.asc())
        .limit(1)
    )
    return db.scalars(statement).first()


def _flags(created: bool) -> dict[str, bool]:
    return {
        "document_record_created": created,
        "document_version_created": False,
        "file_uploaded": False,
        "ingestion_executed": False,
        "chunks_created": False,
        "embeddings_created": False,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "ai_required": False,
        "vector_store_required": False,
        "ai_vector_not_required": True,
    }


def _next_available_actions() -> list[dict[str, Any]]:
    return [
        {
            "action": "attach_document_version",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "not_implemented_in_registration_execution",
        },
        {
            "action": "upload_binary",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "not_implemented_in_registration_execution",
        },
        {
            "action": "schedule_ingestion",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "not_implemented_in_registration_execution",
        },
    ]


def _base_response(payload: DocumentRegistrationRequest, status: str, *, ready: bool) -> dict[str, Any]:
    return {
        "plan": "document_registration_execution",
        "registration_execution_schema_version": DOCUMENT_REGISTRATION_EXECUTION_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "execution_status": status,
        "ready": ready,
        "next_available_actions": _next_available_actions(),
        "idempotency": {
            "mode": "external_reference",
            "external_reference": payload.external_reference,
            "idempotency_key_present": bool(payload.external_reference),
        },
    }


def _already_executed(
    payload: DocumentRegistrationRequest, record: DocumentRecord, status: str = "already_executed"
) -> dict[str, Any]:
    response = _base_response(payload, status, ready=True)
    response.update(
        {
            "document_record_id": str(record.id),
            "existing_document_record_id": str(record.id),
            "created": False,
            "idempotent_replay": True,
            "document_record": _read_record(record),
            "blocking_issues": [],
            "warnings": [],
            "generated_from": {"idempotency_lookup": "documents.document_records.external_reference"},
            **_flags(False),
        }
    )
    response["idempotency"]["existing_document_record_id"] = str(record.id)
    return response


def _blocked(
    payload: DocumentRegistrationRequest, plan: dict[str, Any], issues: list[dict[str, Any]]
) -> dict[str, Any]:
    response = _base_response(payload, "blocked", ready=False)
    response.update(
        {
            "document_record_id": None,
            "existing_document_record_id": plan.get("prevalidation", {}).get("existing_document_record_id"),
            "created": False,
            "idempotent_replay": False,
            "document_record": None,
            "blocking_issues": sorted(
                list(plan.get("blocking_issues") or []) + issues,
                key=lambda item: (item.get("component") or "", item.get("code") or "", str(item.get("item_id"))),
            ),
            "warnings": plan.get("warnings") or [],
            "registration_candidate": plan.get("registration_candidate"),
            "plan_input": plan,
            "generated_from": {"registration_plan": plan.get("plan")},
            **_flags(False),
        }
    )
    response["idempotency"]["existing_document_record_id"] = plan.get("prevalidation", {}).get(
        "existing_document_record_id"
    )
    return response


def _new_record(candidate: dict[str, Any], requested_by: str | None) -> DocumentRecord:
    record = DocumentRecord(
        organization_id=uuid.UUID(candidate["organization_id"]),
        collection_id=uuid.UUID(candidate["collection_id"]) if candidate.get("collection_id") else None,
        document_type_id=uuid.UUID(candidate["document_type_id"]) if candidate.get("document_type_id") else None,
        metadata_template_id=uuid.UUID(candidate["metadata_template_id"])
        if candidate.get("metadata_template_id")
        else None,
        external_reference=candidate.get("external_reference"),
        title=candidate["title"],
        description=candidate.get("description"),
        source_type=candidate["source_type"],
        source_ref=candidate.get("source_ref") or {},
        metadata_json=candidate.get("metadata") or {},
        classification=candidate.get("classification") or {},
        status="registered",
    )
    if requested_by:
        record.created_by = requested_by
        record.updated_by = requested_by
    return record


def build_document_registration_execution(
    db: Session,
    *,
    payload: DocumentRegistrationRequest,
    commit: bool = True,
) -> dict[str, Any]:
    """Create only DocumentRecord by reusing the registration plan."""

    existing = _existing_record(db, payload.organization_id, payload.external_reference)
    if existing is not None:
        return _already_executed(payload, existing)

    plan = build_document_registration_plan(db, payload=payload)
    execution_issues: list[dict[str, Any]] = []
    if not payload.external_reference:
        execution_issues.append(
            _issue(
                "external_reference_required_for_execution",
                "Document registration execution requires external_reference as idempotency key.",
                "document_record",
            )
        )

    if not plan["ready"] or execution_issues:
        return _blocked(payload, plan, execution_issues)

    record = _new_record(plan["registration_candidate"], payload.requested_by)
    db.add(record)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        existing_after_race = _existing_record(db, payload.organization_id, payload.external_reference)
        if existing_after_race is not None:
            return _already_executed(payload, existing_after_race, status="already_executed_after_race")
        raise

    db.refresh(record)
    response = _base_response(payload, "executed", ready=True)
    response.update(
        {
            "document_record_id": str(record.id),
            "existing_document_record_id": None,
            "created": True,
            "idempotent_replay": False,
            "document_record": _read_record(record),
            "blocking_issues": [],
            "warnings": plan.get("warnings") or [],
            "registration_candidate": plan["registration_candidate"],
            "plan_input": plan,
            "generated_from": {"registration_plan": plan["plan"]},
            **_flags(True),
        }
    )
    response["idempotency"]["existing_document_record_id"] = None
    return response
