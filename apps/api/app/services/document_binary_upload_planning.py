"""Non-destructive binary upload planning for future DocumentVersion content attachment."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import DocumentVersion
from app.schemas.documents import DocumentBinaryUploadPlanRequest, DocumentVersionPlanRequest
from app.services.document_management_configuration import build_document_type_configuration_profile
from app.services.document_version_planning import build_document_version_plan

DOCUMENT_BINARY_UPLOAD_PLAN_SCHEMA_VERSION = "1"


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


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return []
    return sorted({str(item) for item in value if str(item).strip()})


def _merge_upload_policy(*configs: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for config in configs:
        if not isinstance(config, dict):
            continue
        candidates = [
            config.get("binary_upload"),
            config.get("upload"),
            (config.get("binary") or {}).get("upload") if isinstance(config.get("binary"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                merged.update(candidate)
    return merged


def _resolve_upload_constraints(
    document_type_profile: dict[str, Any] | None, document_record: dict[str, Any] | None
) -> dict[str, Any]:
    if not document_type_profile or not document_type_profile.get("profile"):
        return {
            "max_size_bytes_allowed": None,
            "allowed_mime_types": [],
            "expected_file_name": None,
            "mime_type_restricted": False,
            "size_limited": False,
        }

    profile = document_type_profile["profile"]
    document_type = profile["document_type"]
    collection_id = (document_record or {}).get("collection_id")
    selected_collection = None
    if collection_id:
        selected_collection = next(
            (item for item in profile["collections"] if item["id"] == collection_id),
            None,
        )
    policy = _merge_upload_policy(
        document_type.get("config") or {},
        (selected_collection or {}).get("config") or {},
    )
    max_size_bytes_allowed = _coerce_int(policy.get("max_size_bytes", policy.get("max_bytes")))
    allowed_mime_types = _coerce_str_list(policy.get("allowed_mime_types", policy.get("allowed_content_types")))
    expected_file_name = policy.get("expected_file_name") or policy.get("file_name_pattern")
    return {
        "max_size_bytes_allowed": max_size_bytes_allowed,
        "allowed_mime_types": allowed_mime_types,
        "expected_file_name": str(expected_file_name) if expected_file_name else None,
        "mime_type_restricted": bool(allowed_mime_types),
        "size_limited": max_size_bytes_allowed is not None,
    }


def _pending_prerequisites(*, document_version_exists: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not document_version_exists:
        items.append(
            {
                "prerequisite": "create_document_version",
                "status": "pending",
                "required_for_upload": True,
                "reason": "document_version_foundation_execution_not_implemented",
            }
        )
    items.extend(
        [
            {
                "prerequisite": "select_storage_backend_binding",
                "status": "pending",
                "required_for_upload": True,
                "reason": "storage_backend_must_remain_abstract_and_configurable",
            },
            {
                "prerequisite": "execute_binary_upload_contract",
                "status": "pending",
                "required_for_upload": True,
                "reason": "binary_upload_execution_not_implemented",
            },
        ]
    )
    return items


def _next_available_actions(*, document_version_exists: bool, upload_allowed: bool) -> list[dict[str, Any]]:
    actions = []
    if not document_version_exists:
        actions.append(
            {
                "action": "create_document_version",
                "available": False,
                "executed": False,
                "status": "not_available",
                "reason": "document_version_execution_not_implemented",
            }
        )
    actions.extend(
        [
            {
                "action": "prepare_binary_upload_execution",
                "available": False,
                "executed": False,
                "status": "ready" if upload_allowed else "blocked",
                "reason": "binary_upload_execution_not_implemented",
            },
            {
                "action": "attach_binary_content",
                "available": False,
                "executed": False,
                "status": "not_available",
                "reason": "storage_backend_binding_missing",
            },
            {
                "action": "schedule_ingestion",
                "available": False,
                "executed": False,
                "status": "not_available",
                "reason": "ingestion_is_future_capability",
            },
        ]
    )
    return actions


def _version_lookup(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_record_id: uuid.UUID,
    document_version_id: uuid.UUID | None,
) -> DocumentVersion | None:
    if document_version_id is None:
        return None
    statement = select(DocumentVersion).where(
        DocumentVersion.id == document_version_id,
        DocumentVersion.organization_id == organization_id,
        DocumentVersion.document_record_id == document_record_id,
    )
    return db.scalar(statement)


def _version_has_binary(version: DocumentVersion) -> bool:
    return any(
        [
            version.object_store_provider,
            version.object_store_bucket,
            version.object_store_key,
            version.checksum_sha256,
            version.file_name,
            version.content_type,
            version.size_bytes is not None,
        ]
    )


def build_document_binary_upload_plan(
    db: Session,
    *,
    payload: DocumentBinaryUploadPlanRequest,
) -> dict[str, Any]:
    """Plan a future binary upload without storing content or binding to a provider."""

    version_plan = build_document_version_plan(
        db,
        payload=DocumentVersionPlanRequest(
            organization_id=payload.organization_id,
            document_record_id=payload.document_record_id,
            metadata=payload.metadata,
        ),
    )
    blocking_issues: list[dict[str, Any]] = list(version_plan["blocking_issues"])
    warnings: list[dict[str, Any]] = list(version_plan["warnings"])
    document_record = version_plan["document_record"]
    document_type_profile: dict[str, Any] | None = None

    if document_record and document_record.get("document_type_id"):
        document_type_profile = build_document_type_configuration_profile(
            db,
            document_type_id=uuid.UUID(document_record["document_type_id"]),
            organization_id=payload.organization_id,
        )

    constraints = _resolve_upload_constraints(document_type_profile, document_record)
    document_version = _version_lookup(
        db,
        organization_id=payload.organization_id,
        document_record_id=payload.document_record_id,
        document_version_id=payload.document_version_id,
    )

    if payload.document_version_id is not None and document_version is None:
        blocking_issues.append(
            _issue(
                "document_version_not_found",
                "DocumentVersion does not exist for the requested document and organization.",
                component="document_version",
                item_id=str(payload.document_version_id),
            )
        )

    if document_version is not None and _version_has_binary(document_version):
        blocking_issues.append(
            _issue(
                "document_version_binary_already_attached",
                "DocumentVersion already contains binary attachment metadata and should not be planned "
                "as a new upload target.",
                component="document_version",
                item_id=str(document_version.id),
            )
        )

    if (
        payload.size_bytes is not None
        and constraints["max_size_bytes_allowed"] is not None
        and payload.size_bytes > constraints["max_size_bytes_allowed"]
    ):
        blocking_issues.append(
            _issue(
                "declared_size_exceeds_maximum",
                "Declared binary size exceeds the configured maximum size.",
                component="binary_upload",
                item_id=str(payload.size_bytes),
            )
        )

    if (
        payload.content_type
        and constraints["allowed_mime_types"]
        and payload.content_type not in constraints["allowed_mime_types"]
    ):
        blocking_issues.append(
            _issue(
                "declared_content_type_not_allowed",
                "Declared MIME type is not permitted by the upload policy.",
                component="binary_upload",
                item_id=payload.content_type,
            )
        )

    expected_file_name = constraints["expected_file_name"] or payload.file_name
    if (
        constraints["expected_file_name"]
        and payload.file_name
        and payload.file_name != constraints["expected_file_name"]
    ):
        warnings.append(
            _warning(
                "declared_file_name_differs_from_expected",
                "Declared file name differs from the configured expected file name.",
                component="binary_upload",
                item_id=payload.file_name,
            )
        )

    blocking_issues = _sort_issues(blocking_issues)
    warnings = _sort_issues(warnings)
    document_version_exists = document_version is not None
    upload_allowed = not blocking_issues and document_version_exists
    upload_blocked = not upload_allowed

    return {
        "plan": "document_binary_upload_plan",
        "document_binary_upload_plan_schema_version": DOCUMENT_BINARY_UPLOAD_PLAN_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "document_record_id": str(payload.document_record_id),
        "document_version_id": str(payload.document_version_id) if payload.document_version_id else None,
        "document_record_exists": version_plan["document_record_exists"],
        "document_version_exists": document_version_exists,
        "document_version_prerequisite_pending": not document_version_exists,
        "upload_allowed": upload_allowed,
        "upload_blocked": upload_blocked,
        "planning_status": "ready" if upload_allowed else "blocked",
        "max_size_bytes_allowed": constraints["max_size_bytes_allowed"],
        "allowed_mime_types": constraints["allowed_mime_types"],
        "expected_file_name": expected_file_name,
        "declared_file_name": payload.file_name,
        "declared_content_type": payload.content_type,
        "declared_size_bytes": payload.size_bytes,
        "document_record": document_record,
        "document_version": _read_version(document_version),
        "version_plan": version_plan,
        "storage_backend_binding": {
            "required": True,
            "selected": None,
            "provider_assumed": False,
            "backend_abstracted": True,
        },
        "pending_prerequisites": _pending_prerequisites(document_version_exists=document_version_exists),
        "next_available_actions": _next_available_actions(
            document_version_exists=document_version_exists,
            upload_allowed=upload_allowed,
        ),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "binary_written": False,
        "storage_object_created": False,
        "checksum_generated": False,
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
            "document_version_plan": version_plan["plan"],
            "document_type_configuration_profile": document_type_profile["plan"] if document_type_profile else None,
        },
    }
