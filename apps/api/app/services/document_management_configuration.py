"""Document Management configuration foundation services.

This module consolidates generic document configuration into deterministic,
read-only platform contracts. It does not execute ingestion, AI, vector
indexing, migrations, remediation or destructive actions.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.documents import (
    ClassificationRule,
    Collection,
    DocumentType,
    MetadataTemplate,
    RetentionPolicy,
)

DOCUMENT_CONFIGURATION_SCHEMA_VERSION = "1"
DOCUMENT_CONFIGURATION_CONTRACT_SCHEMA_VERSION = "1"
DOCUMENT_CONFIGURATION_VALIDATION_SCHEMA_VERSION = "1"
DOCUMENT_TYPE_PROFILE_SCHEMA_VERSION = "1"

CONFIGURATION_COMPONENTS = (
    "document_types",
    "metadata_templates",
    "classification_rules",
    "retention_policies",
    "collections",
)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _uuid(value: Any) -> str | None:
    if isinstance(value, uuid.UUID):
        return str(value)
    return None


def _organization_filter(model: type[Any], organization_id: uuid.UUID | None) -> Any:
    if organization_id is None:
        return model.organization_id.is_(None)
    return or_(model.organization_id.is_(None), model.organization_id == organization_id)


def _ordered(statement: Any, model: type[Any]) -> Any:
    return statement.order_by(model.organization_id.asc().nullsfirst(), model.code.asc(), model.id.asc())


def _fetch(db: Session, model: type[Any], organization_id: uuid.UUID | None) -> list[Any]:
    statement = select(model).where(_organization_filter(model, organization_id))
    return list(db.scalars(_ordered(statement, model)).all())


def _base_config_item(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "organization_id": _uuid(item.organization_id),
        "scope": "global" if item.organization_id is None else "organization",
        "code": item.code,
        "name": item.name,
        "status": item.status,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _document_type(item: DocumentType) -> dict[str, Any]:
    payload = _base_config_item(item)
    payload.update(
        {
            "description": item.description,
            "version": item.version,
            "config": item.config or {},
        }
    )
    return payload


def _metadata_template(item: MetadataTemplate) -> dict[str, Any]:
    payload = _base_config_item(item)
    payload.update(
        {
            "document_type_id": _uuid(item.document_type_id),
            "schema_definition": item.schema_definition or {},
        }
    )
    return payload


def _policy_rule(item: RetentionPolicy | ClassificationRule) -> dict[str, Any]:
    payload = _base_config_item(item)
    payload.update({"rules": item.rules or {}})
    return payload


def _collection(item: Collection) -> dict[str, Any]:
    payload = _base_config_item(item)
    payload.update(
        {
            "description": item.description,
            "vector_provider": item.vector_provider,
            "vector_collection_name": item.vector_collection_name,
            "config": item.config or {},
            "ai_required": False,
            "vector_store_required": False,
        }
    )
    return payload


def _active(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("status") == "active"]


def _component_summary(items: list[dict[str, Any]], *, blocking: bool) -> dict[str, Any]:
    active = _active(items)
    return {
        "configured": bool(items),
        "ready": bool(active),
        "blocking": blocking,
        "count": len(items),
        "active_count": len(active),
        "inactive_count": len(items) - len(active),
    }


def build_document_configuration_catalog(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build the generic Document Management configuration catalog."""

    document_types = [_document_type(item) for item in _fetch(db, DocumentType, organization_id)]
    metadata_templates = [_metadata_template(item) for item in _fetch(db, MetadataTemplate, organization_id)]
    classification_rules = [_policy_rule(item) for item in _fetch(db, ClassificationRule, organization_id)]
    retention_policies = [_policy_rule(item) for item in _fetch(db, RetentionPolicy, organization_id)]
    collections = [_collection(item) for item in _fetch(db, Collection, organization_id)]
    return {
        "plan": "document_management_configuration_catalog",
        "configuration_schema_version": DOCUMENT_CONFIGURATION_SCHEMA_VERSION,
        "organization_id": _uuid(organization_id),
        "components": {
            "document_types": document_types,
            "metadata_templates": metadata_templates,
            "classification_rules": classification_rules,
            "retention_policies": retention_policies,
            "collections": collections,
        },
        "ai_required": False,
        "vector_store_required": False,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_document_configuration_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    """Build readiness summary from a configuration catalog."""

    components = catalog["components"]
    component_readiness = {
        "document_types": _component_summary(components["document_types"], blocking=True),
        "metadata_templates": _component_summary(components["metadata_templates"], blocking=True),
        "classification_rules": _component_summary(components["classification_rules"], blocking=True),
        "retention_policies": _component_summary(components["retention_policies"], blocking=True),
        "collections": _component_summary(components["collections"], blocking=True),
    }
    blocking_components = [name for name, item in component_readiness.items() if item["blocking"] and not item["ready"]]
    optional_degradations = [
        name for name, item in component_readiness.items() if not item["blocking"] and not item["ready"]
    ]
    return {
        "plan": "document_management_configuration_summary",
        "configuration_schema_version": DOCUMENT_CONFIGURATION_SCHEMA_VERSION,
        "organization_id": catalog["organization_id"],
        "ready": not blocking_components,
        "document_management_blocking": True,
        "ai_required": False,
        "vector_store_required": False,
        "blocking_components": blocking_components,
        "optional_degradations": optional_degradations,
        "components": component_readiness,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_document_configuration_validation(catalog: dict[str, Any]) -> dict[str, Any]:
    """Validate internal consistency of generic document configuration."""

    components = catalog["components"]
    document_type_ids = {item["id"] for item in components["document_types"]}
    active_document_type_ids = {item["id"] for item in components["document_types"] if item["status"] == "active"}
    issues: list[dict[str, Any]] = []

    for template in components["metadata_templates"]:
        document_type_id = template.get("document_type_id")
        if document_type_id and document_type_id not in document_type_ids:
            issues.append(
                {
                    "code": "metadata_template_document_type_missing",
                    "severity": "blocking",
                    "component": "metadata_templates",
                    "item_id": template["id"],
                    "message": "Metadata template references a document type outside the configuration catalog.",
                }
            )
        elif document_type_id and document_type_id not in active_document_type_ids:
            issues.append(
                {
                    "code": "metadata_template_document_type_inactive",
                    "severity": "warning",
                    "component": "metadata_templates",
                    "item_id": template["id"],
                    "message": "Metadata template references an inactive document type.",
                }
            )

    for collection in components["collections"]:
        has_provider = bool(collection.get("vector_provider"))
        has_name = bool(collection.get("vector_collection_name"))
        if has_provider != has_name:
            issues.append(
                {
                    "code": "collection_vector_configuration_partial",
                    "severity": "warning",
                    "component": "collections",
                    "item_id": collection["id"],
                    "message": "Collection has partial optional vector configuration.",
                }
            )

    summary = build_document_configuration_summary(catalog)
    for component in summary["blocking_components"]:
        issues.append(
            {
                "code": f"{component}_not_ready",
                "severity": "blocking",
                "component": component,
                "item_id": None,
                "message": "Required Document Management configuration component has no active entries.",
            }
        )

    issues = sorted(issues, key=lambda item: (item["severity"], item["component"], item["code"], str(item["item_id"])))
    blocking_issues = [item for item in issues if item["severity"] == "blocking"]
    warnings = [item for item in issues if item["severity"] != "blocking"]
    return {
        "plan": "document_management_configuration_validation",
        "configuration_validation_schema_version": DOCUMENT_CONFIGURATION_VALIDATION_SCHEMA_VERSION,
        "organization_id": catalog["organization_id"],
        "valid": not blocking_issues,
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking_issues),
        "warning_count": len(warnings),
        "issues": issues,
        "ai_required": False,
        "vector_store_required": False,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_document_configuration_contract(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build the reusable Document Management configuration contract."""

    catalog = build_document_configuration_catalog(db, organization_id=organization_id)
    summary = build_document_configuration_summary(catalog)
    validation = build_document_configuration_validation(catalog)
    return {
        "plan": "document_management_configuration_contract",
        "configuration_contract_schema_version": DOCUMENT_CONFIGURATION_CONTRACT_SCHEMA_VERSION,
        "organization_id": catalog["organization_id"],
        "ready": bool(summary["ready"] and validation["valid"]),
        "document_management_blocking": True,
        "ai_required": False,
        "vector_store_required": False,
        "components": summary["components"],
        "blocking_components": summary["blocking_components"],
        "optional_degradations": summary["optional_degradations"],
        "validation": validation,
        "catalog": catalog,
        "generated_from": {
            "catalog": catalog["plan"],
            "summary": summary["plan"],
            "validation": validation["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_document_type_configuration_profile(
    db: Session,
    *,
    document_type_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Resolve configuration that applies to one configurable document type."""

    catalog = build_document_configuration_catalog(db, organization_id=organization_id)
    document_type_id_text = str(document_type_id)
    matching = [item for item in catalog["components"]["document_types"] if item["id"] == document_type_id_text]
    if not matching:
        return {
            "plan": "document_type_configuration_profile",
            "document_type_profile_schema_version": DOCUMENT_TYPE_PROFILE_SCHEMA_VERSION,
            "organization_id": catalog["organization_id"],
            "document_type_id": document_type_id_text,
            "found": False,
            "ready": False,
            "blocking_issues": ["document_type_not_found"],
            "profile": None,
            "destructive_action_executed": False,
            "migration_executed": False,
            "downgrade_executed": False,
        }

    document_type = matching[0]
    metadata_templates = [
        item
        for item in catalog["components"]["metadata_templates"]
        if item.get("document_type_id") in {None, document_type_id_text}
    ]
    active_metadata_templates = _active(metadata_templates)
    active_classification_rules = _active(catalog["components"]["classification_rules"])
    active_retention_policies = _active(catalog["components"]["retention_policies"])
    active_collections = _active(catalog["components"]["collections"])
    blocking_issues: list[str] = []
    if document_type["status"] != "active":
        blocking_issues.append("document_type_inactive")
    if not active_metadata_templates:
        blocking_issues.append("metadata_template_missing")
    if not active_classification_rules:
        blocking_issues.append("classification_rule_missing")
    if not active_retention_policies:
        blocking_issues.append("retention_policy_missing")
    if not active_collections:
        blocking_issues.append("collection_missing")

    return {
        "plan": "document_type_configuration_profile",
        "document_type_profile_schema_version": DOCUMENT_TYPE_PROFILE_SCHEMA_VERSION,
        "organization_id": catalog["organization_id"],
        "document_type_id": document_type_id_text,
        "found": True,
        "ready": not blocking_issues,
        "blocking_issues": blocking_issues,
        "profile": {
            "document_type": document_type,
            "metadata_templates": active_metadata_templates,
            "classification_rules": active_classification_rules,
            "retention_policies": active_retention_policies,
            "collections": active_collections,
        },
        "ai_required": False,
        "vector_store_required": False,
        "generated_from": {
            "catalog": catalog["plan"],
        },
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }
