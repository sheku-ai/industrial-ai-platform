"""Non-destructive Document Management registration planning services."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import DocumentRecord
from app.schemas.documents import DocumentRegistrationRequest
from app.services.document_management_configuration import (
    build_document_configuration_contract,
    build_document_type_configuration_profile,
)

DOCUMENT_REGISTRATION_SCHEMA_VERSION = "1"
REQUIRED_CONFIGURATION = (
    "document_type",
    "metadata_template",
    "classification_rule",
    "retention_policy",
    "collection",
)


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


def _select_by_id(
    items: list[dict[str, Any]],
    requested_id: uuid.UUID | None,
    *,
    component: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if requested_id is None:
        active = [item for item in items if item.get("status") == "active"]
        return (active[0] if active else None), []

    requested = str(requested_id)
    matches = [item for item in items if item["id"] == requested]
    if not matches:
        return None, [
            _issue(
                f"{component}_not_found",
                "Requested configuration item was not found.",
                component=component,
                item_id=requested,
            )
        ]
    if matches[0].get("status") != "active":
        return matches[0], [
            _issue(
                f"{component}_inactive",
                "Requested configuration item is not active.",
                component=component,
                item_id=requested,
            )
        ]
    return matches[0], []


def _select_metadata_template(
    items: list[dict[str, Any]],
    requested_id: uuid.UUID | None,
    *,
    document_type_id: uuid.UUID,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    document_type_id_text = str(document_type_id)
    applicable = [item for item in items if item.get("document_type_id") in {None, document_type_id_text}]
    if requested_id is None:
        active = [item for item in applicable if item.get("status") == "active"]
        active = sorted(
            active,
            key=lambda item: (
                item.get("document_type_id") != document_type_id_text,
                item.get("code") or "",
                item["id"],
            ),
        )
        return (active[0] if active else None), []

    requested = str(requested_id)
    matches = [item for item in items if item["id"] == requested]
    if not matches:
        return None, [
            _issue(
                "metadata_template_not_found",
                "Requested metadata template was not found.",
                component="metadata_template",
                item_id=requested,
            )
        ]
    selected = matches[0]
    issues: list[dict[str, Any]] = []
    if selected.get("status") != "active":
        issues.append(
            _issue(
                "metadata_template_inactive",
                "Requested metadata template is not active.",
                component="metadata_template",
                item_id=requested,
            )
        )
    if selected.get("document_type_id") not in {None, document_type_id_text}:
        issues.append(
            _issue(
                "metadata_template_not_applicable",
                "Requested metadata template does not apply to the selected document type.",
                component="metadata_template",
                item_id=requested,
            )
        )
    return selected, issues


def _required_fields_from_definition(definition: Any) -> list[str]:
    if not isinstance(definition, dict):
        return []
    required = definition.get("required", definition.get("required_fields", []))
    if not isinstance(required, list):
        return []
    return sorted(field for field in required if isinstance(field, str))


def _metadata_required_fields(template: dict[str, Any] | None) -> list[str]:
    if not template:
        return []
    return _required_fields_from_definition(template.get("schema_definition") or {})


def _classification_required_fields(rule: dict[str, Any] | None) -> list[str]:
    if not rule:
        return []
    return _required_fields_from_definition(rule.get("rules") or {})


def _missing_fields(required: list[str], values: dict[str, Any]) -> list[str]:
    return sorted(field for field in required if field not in values)


def _existing_document_record_id(
    db: Session,
    *,
    organization_id: uuid.UUID,
    external_reference: str | None,
) -> str | None:
    if not external_reference:
        return None
    statement = (
        select(DocumentRecord.id)
        .where(DocumentRecord.organization_id == organization_id)
        .where(DocumentRecord.external_reference == external_reference)
        .order_by(DocumentRecord.id.asc())
        .limit(1)
    )
    existing_id = db.scalar(statement)
    return str(existing_id) if existing_id is not None else None


def _registration_candidate(
    payload: DocumentRegistrationRequest,
    selected: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    return {
        "organization_id": str(payload.organization_id),
        "collection_id": selected["collection"]["id"] if selected["collection"] else None,
        "document_type_id": selected["document_type"]["id"] if selected["document_type"] else None,
        "metadata_template_id": selected["metadata_template"]["id"] if selected["metadata_template"] else None,
        "external_reference": payload.external_reference,
        "title": payload.title,
        "description": payload.description,
        "source_type": payload.source_type,
        "source_ref": payload.source_ref,
        "metadata": payload.metadata,
        "classification": payload.classification,
        "status": "registered",
    }


def build_document_registration_prevalidation(
    db: Session,
    *,
    payload: DocumentRegistrationRequest,
) -> dict[str, Any]:
    """Validate a future document registration without changing state."""

    contract = build_document_configuration_contract(db, organization_id=payload.organization_id)
    profile = build_document_type_configuration_profile(
        db,
        document_type_id=payload.document_type_id,
        organization_id=payload.organization_id,
    )
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    missing_configuration: list[str] = []

    for component in contract["blocking_components"]:
        missing_configuration.append(component)
        blocking_issues.append(
            _issue(
                f"{component}_not_ready",
                "Required Document Management configuration component is not ready.",
                component=component,
            )
        )

    validation = contract["validation"]
    for item in validation["issues"]:
        if item["severity"] == "blocking":
            blocking_issues.append(item)
        else:
            warnings.append(item)

    selected_document_type = None
    selected_metadata_template = None
    selected_classification_rule = None
    selected_retention_policy = None
    selected_collection = None

    if not profile["found"]:
        missing_configuration.append("document_type")
        blocking_issues.append(
            _issue(
                "document_type_not_found",
                "Selected document type was not found in the applicable configuration.",
                component="document_type",
                item_id=str(payload.document_type_id),
            )
        )
    elif profile["profile"] is not None:
        selected_document_type = profile["profile"]["document_type"]
        if selected_document_type.get("status") != "active":
            blocking_issues.append(
                _issue(
                    "document_type_inactive",
                    "Selected document type is not active.",
                    component="document_type",
                    item_id=selected_document_type["id"],
                )
            )
        selected_metadata_template, metadata_issues = _select_metadata_template(
            profile["profile"]["metadata_templates"],
            payload.metadata_template_id,
            document_type_id=payload.document_type_id,
        )
        selected_classification_rule, classification_issues = _select_by_id(
            profile["profile"]["classification_rules"],
            payload.classification_rule_id,
            component="classification_rule",
        )
        selected_retention_policy, retention_issues = _select_by_id(
            profile["profile"]["retention_policies"],
            payload.retention_policy_id,
            component="retention_policy",
        )
        selected_collection, collection_issues = _select_by_id(
            profile["profile"]["collections"],
            payload.collection_id,
            component="collection",
        )
        blocking_issues.extend(metadata_issues)
        blocking_issues.extend(classification_issues)
        blocking_issues.extend(retention_issues)
        blocking_issues.extend(collection_issues)

    selected = {
        "document_type": selected_document_type,
        "metadata_template": selected_metadata_template,
        "classification_rule": selected_classification_rule,
        "retention_policy": selected_retention_policy,
        "collection": selected_collection,
    }

    for component, item in selected.items():
        if item is None:
            missing_configuration.append(component)
            blocking_issues.append(
                _issue(
                    f"{component}_missing",
                    "Required registration configuration was not selected or available.",
                    component=component,
                )
            )

    metadata_required_fields = _metadata_required_fields(selected_metadata_template)
    missing_metadata_fields = _missing_fields(metadata_required_fields, payload.metadata)
    for field in missing_metadata_fields:
        blocking_issues.append(
            _issue(
                "metadata_required_field_missing",
                "Required metadata field is missing from the registration request.",
                component="metadata",
                item_id=field,
            )
        )
    classification_required_fields = _classification_required_fields(selected_classification_rule)
    missing_classification_fields = _missing_fields(classification_required_fields, payload.classification)
    for field in missing_classification_fields:
        blocking_issues.append(
            _issue(
                "classification_required_field_missing",
                "Required classification field is missing from the registration request.",
                component="classification",
                item_id=field,
            )
        )

    existing_document_record_id = _existing_document_record_id(
        db,
        organization_id=payload.organization_id,
        external_reference=payload.external_reference,
    )
    if existing_document_record_id:
        blocking_issues.append(
            _issue(
                "external_reference_already_registered",
                "External reference is already registered for this organization.",
                component="document_record",
                item_id=existing_document_record_id,
            )
        )

    if not payload.source_ref:
        warnings.append(
            _warning(
                "source_ref_empty",
                "Registration request has no source reference details.",
                component="source_ref",
            )
        )

    blocking_issues = _sort_issues(blocking_issues)
    warnings = _sort_issues(warnings)
    missing_configuration = sorted(set(missing_configuration))
    validation_status = "blocked" if blocking_issues else ("valid_with_warnings" if warnings else "valid")

    return {
        "plan": "document_registration_prevalidation",
        "registration_schema_version": DOCUMENT_REGISTRATION_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "validation_status": validation_status,
        "ready": not blocking_issues,
        "selected_document_type": selected_document_type,
        "metadata_template": selected_metadata_template,
        "classification_rule": selected_classification_rule,
        "retention_policy": selected_retention_policy,
        "collection": selected_collection,
        "selected_configuration": selected,
        "required_configuration": list(REQUIRED_CONFIGURATION),
        "missing_configuration": missing_configuration,
        "metadata_validation": {
            "required_fields": metadata_required_fields,
            "missing_required_fields": missing_metadata_fields,
        },
        "classification_validation": {
            "required_fields": classification_required_fields,
            "missing_required_fields": missing_classification_fields,
        },
        "registration_candidate": _registration_candidate(payload, selected),
        "existing_document_record_id": existing_document_record_id,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "ai_required": False,
        "vector_store_required": False,
        "ai_vector_not_required": True,
        "document_record_created": False,
        "document_version_created": False,
        "file_uploaded": False,
        "ingestion_executed": False,
        "chunks_created": False,
        "embeddings_created": False,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "generated_from": {
            "document_configuration_contract": contract["plan"],
            "document_type_configuration_profile": profile["plan"],
        },
    }


def build_document_registration_plan(
    db: Session,
    *,
    payload: DocumentRegistrationRequest,
) -> dict[str, Any]:
    """Build a deterministic, non-destructive plan for future document registration."""

    prevalidation = build_document_registration_prevalidation(db, payload=payload)
    plan_status = "ready" if prevalidation["ready"] else "blocked"
    return {
        "plan": "document_registration_plan",
        "registration_schema_version": DOCUMENT_REGISTRATION_SCHEMA_VERSION,
        "organization_id": str(payload.organization_id),
        "plan_status": plan_status,
        "ready": prevalidation["ready"],
        "validation_status": prevalidation["validation_status"],
        "selected_document_type": prevalidation["selected_document_type"],
        "metadata_template": prevalidation["metadata_template"],
        "classification_rule": prevalidation["classification_rule"],
        "retention_policy": prevalidation["retention_policy"],
        "collection": prevalidation["collection"],
        "selected_configuration": prevalidation["selected_configuration"],
        "required_configuration": prevalidation["required_configuration"],
        "missing_configuration": prevalidation["missing_configuration"],
        "blocking_issues": prevalidation["blocking_issues"],
        "warnings": prevalidation["warnings"],
        "registration_candidate": prevalidation["registration_candidate"],
        "future_execution": {
            "would_create_document_record": prevalidation["ready"],
            "would_create_document_version": False,
            "would_upload_binary": False,
            "would_execute_ingestion": False,
            "would_create_chunks": False,
            "would_create_embeddings": False,
            "would_index_vector_store": False,
        },
        "operator_steps": [
            {
                "step": "review_registration_prevalidation",
                "required": True,
                "status": "ready" if prevalidation["ready"] else "blocked",
            },
            {
                "step": "execute_future_document_record_registration",
                "required": True,
                "status": "not_executed",
            },
            {
                "step": "attach_binary_and_start_ingestion_when_needed",
                "required": False,
                "status": "not_executed",
            },
        ],
        "ai_required": False,
        "vector_store_required": False,
        "ai_vector_not_required": True,
        "document_record_created": False,
        "document_version_created": False,
        "file_uploaded": False,
        "ingestion_executed": False,
        "chunks_created": False,
        "embeddings_created": False,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
        "prevalidation": prevalidation,
        "generated_from": {
            "prevalidation": prevalidation["plan"],
        },
    }
