"""Non-destructive DocumentVersion planning services."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.documents import DocumentRecord, DocumentVersion
from app.schemas.documents import DocumentVersionPlanRequest
from app.services.document_management_configuration import (
    build_document_configuration_contract,
    build_document_type_configuration_profile,
)

DOCUMENT_VERSION_PLAN_SCHEMA_VERSION = "1"


def _issue(code: str, message: str, *, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "blocking",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _warning(code: str, message: str, *, component: str, item_id: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "warning",
        "component": component,
        "item_id": item_id,
        "message": message,
    }


def _sort_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["component"], item["code"], str(item.get("item_id"))))


def _read_document_record(record: DocumentRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
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
    }


def _latest_version(db: Session, document_record_id: uuid.UUID) -> DocumentVersion | None:
    statement = (
        select(DocumentVersion)
        .where(DocumentVersion.document_record_id == document_record_id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.id.desc())
        .limit(1)
    )
    return db.scalar(statement)


def _version_count(db: Session, document_record_id: uuid.UUID) -> int:
    value = db.scalar(
        select(func.count(DocumentVersion.id)).where(DocumentVersion.document_record_id == document_record_id)
    )
    return int(value or 0)


def _read_version(version: DocumentVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "id": str(version.id),
        "organization_id": str(version.organization_id),
        "document_record_id": str(version.document_record_id),
        "version_number": version.version_number,
        "version_label": version.version_label,
        "status": version.status,
        "content_type": version.content_type,
        "file_name": version.file_name,
        "size_bytes": version.size_bytes,
        "checksum_sha256": version.checksum_sha256,
        "object_store_provider": version.object_store_provider,
        "object_store_bucket": version.object_store_bucket,
        "object_store_key": version.object_store_key,
        "source_snapshot": version.source_snapshot or {},
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
    }


def _pending_prerequisites() -> list[dict[str, Any]]:
    return [
        {
            "prerequisite": "attach_document_version_execution",
            "status": "pending",
            "required_for_plan": False,
            "reason": "version_planning_is_non_destructive",
        },
        {
            "prerequisite": "upload_binary",
            "status": "pending",
            "required_for_plan": False,
            "reason": "upload_is_future_capability",
        },
        {
            "prerequisite": "schedule_ingestion",
            "status": "pending",
            "required_for_plan": False,
            "reason": "ingestion_is_future_capability",
        },
    ]


def _future_actions() -> list[dict[str, Any]]:
    return [
        {
            "action": "create_document_version",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "execution_not_implemented_in_version_foundation",
        },
        {
            "action": "upload_binary",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "upload_not_implemented_in_version_foundation",
        },
        {
            "action": "schedule_ingestion",
            "available": False,
            "executed": False,
            "status": "not_available",
            "reason": "ingestion_not_implemented_in_version_foundation",
        },
    ]


def _version_candidate(
    payload: DocumentVersionPlanRequest,
    *,
    document_record: DocumentRecord | None,
    next_version_number: int | None,
) -> dict[str, Any] | None:
    if document_record is None or next_version_number is None:
        return None
    return {
        "organization_id": str(payload.organization_id),
        "document_record_id": str(document_record.id),
        "version_number": next_version_number,
        "version_label": payload.version_label,
        "status": "registered",
        "content_type": None,
        "file_name": None,
        "size_bytes": None,
        "checksum_sha256": None,
        "object_store_provider": None,
        "object_store_bucket": None,
        "object_store_key": None,
        "source_snapshot": {
            "version_plan": "document_version_foundation_v1",
            "requested_by": payload.requested_by,
            "binary_attached": False,
            "upload_executed": False,
            "ingestion_requested": False,
            "metadata": payload.metadata,
        },
    }


def build_document_version_plan(db: Session, *, payload: DocumentVersionPlanRequest) -> dict[str, Any]:
    """Plan a future DocumentVersion without creating records or uploading binaries."""

    contract = build_document_configuration_contract(db, organization_id=payload.organization_id)
    document_record = db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.id == payload.document_record_id,
            DocumentRecord.organization_id == payload.organization_id,
        )
    )
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for component in contract["blocking_components"]:
        blocking_issues.append(
            _issue(
                f"{component}_not_ready",
                "Required Document Management configuration component is not ready.",
                component=component,
            )
        )
    for item in contract["validation"]["issues"]:
        if item["severity"] == "blocking":
            blocking_issues.append(item)
        else:
            warnings.append(item)

    document_type_profile: dict[str, Any] | None = None
    if document_record is None:
        blocking_issues.append(
            _issue(
                "document_record_not_found",
                "DocumentRecord does not exist for the requested organization.",
                component="document_record",
                item_id=str(payload.document_record_id),
            )
        )
    elif document_record.document_type_id is not None:
        document_type_profile = build_document_type_configuration_profile(
            db,
            document_type_id=document_record.document_type_id,
            organization_id=payload.organization_id,
        )
        if not document_type_profile["ready"]:
            for code in document_type_profile["blocking_issues"]:
                blocking_issues.append(
                    _issue(
                        code,
                        "Document type configuration profile is not ready for version planning.",
                        component="document_type_profile",
                        item_id=str(document_record.document_type_id),
                    )
                )
    else:
        warnings.append(
            _warning(
                "document_record_without_document_type",
                "DocumentRecord has no configured document type.",
                component="document_record",
                item_id=str(document_record.id),
            )
        )

    latest = _latest_version(db, payload.document_record_id) if document_record is not None else None
    version_count = _version_count(db, payload.document_record_id) if document_record is not None else 0
    next_version_number = (
        (latest.version_number if latest is not None else 0) + 1 if document_record is not None else None
    )
    blocking_issues = _sort_issues(blocking_issues)
    warnings = _sort_issues(warnings)
    can_create = not blocking_issues

    return {
        "plan": "document_version_plan",
        "document_version_plan_schema_version": DOCUMENT_VERSION_PLAN_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "document_record_id": str(payload.document_record_id),
        "document_record_exists": document_record is not None,
        "can_create_new_version": can_create,
        "planning_status": "ready" if can_create else "blocked",
        "next_version_number": next_version_number,
        "initial_status": "registered" if can_create else None,
        "document_record": _read_document_record(document_record),
        "latest_version": _read_version(latest),
        "existing_version_count": version_count,
        "version_candidate": _version_candidate(
            payload,
            document_record=document_record,
            next_version_number=next_version_number,
        ),
        "pending_prerequisites": _pending_prerequisites(),
        "next_available_actions": _future_actions(),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "document_version_created": False,
        "file_uploaded": False,
        "artifact_created": False,
        "ingestion_executed": False,
        "chunks_created": False,
        "embeddings_created": False,
        "workflow_executed": False,
        "ai_required": False,
        "vector_store_required": False,
        "ai_vector_not_required": True,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "generated_from": {
            "document_configuration_contract": contract["plan"],
            "document_type_configuration_profile": document_type_profile["plan"] if document_type_profile else None,
        },
    }
