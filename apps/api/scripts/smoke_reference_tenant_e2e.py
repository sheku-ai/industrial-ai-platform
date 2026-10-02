#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")


def http_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API_BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8")
        try:
            parsed: Any = json.loads(details)
        except json.JSONDecodeError:
            parsed = details
        return {"_http_error": True, "status_code": exc.code, "details": parsed}
    except urllib.error.URLError as exc:
        return {"_http_error": True, "error": "connection_failed", "details": str(exc)}


def asset_counts(status_payload: dict[str, Any]) -> dict[str, int]:
    organization_count = 1 if status_payload.get("organization") else 0
    reference_documents = status_payload.get("reference_documents") or []
    knowledge_document_ids = {
        document_id
        for item in reference_documents
        for document_id in (
            item.get("knowledge_document_ids")
            or ([item.get("knowledge_document_id")] if item.get("knowledge_document_id") else [])
        )
        if document_id
    }
    return {
        "organization": organization_count,
        "roles": len(status_payload.get("roles") or []),
        "permissions": len(status_payload.get("permissions") or []),
        "policies": len(status_payload.get("policies") or []),
        "role_assignments": len(status_payload.get("role_assignments") or []),
        "collections": len(status_payload.get("collections") or []),
        "knowledge_sources": len(status_payload.get("knowledge_sources") or []),
        "document_types": len(status_payload.get("document_types") or []),
        "metadata_templates": len(status_payload.get("metadata_templates") or []),
        "retention_policies": len(status_payload.get("retention_policies") or []),
        "classification_rules": len(status_payload.get("classification_rules") or []),
        "assistants": len(status_payload.get("assistants") or []),
        "prompts": len(status_payload.get("prompts") or []),
        "guardrails": len(status_payload.get("guardrails") or []),
        "workflows": len(status_payload.get("workflows") or []),
        "reference_documents": len(reference_documents),
        "document_versions": len([item for item in reference_documents if item.get("document_version_id")]),
        "artifacts": len([item for item in reference_documents if item.get("artifact_id")]),
        "knowledge_records": len(knowledge_document_ids),
    }


def main() -> int:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    readiness_before = http_json("GET", "/reference-tenant/readiness")
    readiness_returned = not readiness_before.get("_http_error")

    provision = http_json("POST", "/reference-tenant/provision", {})
    provision_passed = bool(provision.get("passed")) and not provision.get("_http_error")
    warnings.extend(provision.get("warnings") or [])
    warnings.extend(provision.get("pending_capabilities") or [])

    status = http_json("GET", "/reference-tenant/status")
    status_returned = not status.get("_http_error")
    counts_before_second = asset_counts(status) if status_returned else {}

    assets = http_json("GET", "/reference-tenant/assets")
    assets_returned = not assets.get("_http_error")

    validation = http_json("POST", "/reference-tenant/validate", {})
    validation_passed = bool(validation.get("passed")) and not validation.get("_http_error")
    warnings.extend(validation.get("warnings") or [])
    warnings.extend(validation.get("pending_capabilities") or [])

    provision_second = http_json("POST", "/reference-tenant/provision", {})
    second_passed = bool(provision_second.get("passed")) and not provision_second.get("_http_error")

    status_after = http_json("GET", "/reference-tenant/status")
    validation_after = http_json("POST", "/reference-tenant/validate", {})
    final_validation = validation_after if not validation_after.get("_http_error") else validation
    validation_passed = bool(final_validation.get("passed")) and not final_validation.get("_http_error")
    if final_validation is not validation:
        warnings.extend(final_validation.get("warnings") or [])
        warnings.extend(final_validation.get("pending_capabilities") or [])
    counts_after_second = asset_counts(status_after) if not status_after.get("_http_error") else {}
    effective_status = status_after if not status_after.get("_http_error") else status
    effective_reference_documents = effective_status.get("reference_documents") or []
    readiness = (
        effective_status.get("readiness_summary")
        or final_validation.get("readiness")
        or provision.get("readiness")
        or {}
    )
    knowledge_document_ids = sorted(
        {
            document_id
            for item in effective_reference_documents
            for document_id in (
                item.get("knowledge_document_ids")
                or ([item.get("knowledge_document_id")] if item.get("knowledge_document_id") else [])
            )
            if document_id
        }
    )
    knowledge_chunk_count = sum(
        int(item.get("knowledge_chunk_count") or item.get("knowledge_index_count") or 0)
        for item in effective_reference_documents
    )
    knowledge_index_status = [
        {
            "logical_key": item.get("logical_key"),
            "status": item.get("knowledge_index_status"),
            "knowledge_indexed": item.get("knowledge_indexed"),
            "knowledge_document_ids": item.get("knowledge_document_ids")
            or ([item.get("knowledge_document_id")] if item.get("knowledge_document_id") else []),
            "knowledge_chunk_count": item.get("knowledge_chunk_count") or item.get("knowledge_index_count") or 0,
            "search_result_count": item.get("search_result_count"),
        }
        for item in effective_reference_documents
    ]
    knowledge_index_blocking_issues = [
        issue
        for item in effective_reference_documents
        for issue in item.get("knowledge_index_blocking_issues") or []
        if isinstance(issue, dict)
    ]
    knowledge_index_warnings = [
        warning
        for item in effective_reference_documents
        for warning in item.get("knowledge_index_warnings") or []
        if isinstance(warning, dict)
    ]
    search_index_contract_inconsistent = bool(
        readiness.get("search_index_contract_inconsistent")
        or any(item.get("search_index_contract_inconsistent") for item in effective_reference_documents)
    )
    duplicate_risks = final_validation.get("duplicate_risks") or []
    duplicate_assets_detected = bool(duplicate_risks)
    idempotency_verified = (
        bool(counts_before_second)
        and counts_before_second == counts_after_second
        and second_passed
        and not duplicate_assets_detected
    )

    domain_results = readiness.get("domain_results") or final_validation.get("domain_results") or {}
    warning_codes = {item.get("code") for item in warnings if isinstance(item, dict)}
    forbidden_warning_codes = {
        "reference_content_not_provisioned",
        "search_not_ready_without_reference_content",
        "chat_not_ready_without_reference_content",
    }
    forbidden_warnings_present = sorted(code for code in forbidden_warning_codes if code in warning_codes)
    reference_documents_count = int(readiness.get("reference_documents_count") or len(effective_reference_documents))
    lifecycle_diagnostics = effective_status.get("document_lifecycle_results") or []
    knowledge_records = int((counts_after_second or counts_before_second).get("knowledge_records") or 0)
    checks = {
        "provision_passed": provision_passed,
        "validation_passed": validation_passed,
        "readiness_returned": readiness_returned,
        "status_returned": status_returned,
        "assets_returned": assets_returned,
        "organization_ready": bool(readiness.get("organization_ready")),
        "security_ready": bool(readiness.get("security_ready")),
        "knowledge_ready": bool(readiness.get("knowledge_ready")),
        "documents_ready": bool(readiness.get("documents_ready")),
        "assistant_ready": bool(readiness.get("assistant_ready")),
        "knowledge_source_ready": bool(readiness.get("knowledge_source_ready")),
        "feedback_ready": bool(readiness.get("feedback_ready")),
        "audit_ready": bool(readiness.get("audit_ready")),
        "search_ready": bool(readiness.get("search_ready")),
        "chat_ready": bool(readiness.get("chat_ready")),
        "reference_content_provisioned": bool(readiness.get("reference_content_provisioned")),
        "reference_documents_present": reference_documents_count > 0,
        "knowledge_records_present": knowledge_records > 0,
        "knowledge_indexed": bool(readiness.get("knowledge_indexed")),
        "enterprise_search_ready": bool(readiness.get("enterprise_search_ready")),
        "product_baseline_ready": bool(final_validation.get("product_baseline_ready")),
        "storage_reused_route_accepted": bool(
            readiness.get("knowledge_indexed")
            and readiness.get("enterprise_search_ready")
            and readiness.get("search_ready")
            and readiness.get("chat_ready")
        ),
        "postgresql_source_of_truth": readiness.get("postgresql_source_of_truth") is True,
        "idempotency_verified": idempotency_verified,
        "duplicate_assets_detected": duplicate_assets_detected,
        "search_index_contract_inconsistent": search_index_contract_inconsistent,
        "forbidden_warnings_present": bool(forbidden_warnings_present),
        "llm_used": provision.get("llm_used") is True,
        "embeddings_used": provision.get("embeddings_used") is True,
        "qdrant_used": provision.get("qdrant_used") is True,
    }

    if checks["llm_used"]:
        errors.append({"code": "llm_used", "message": "Reference tenant smoke must not use LLM execution."})
    if checks["embeddings_used"]:
        errors.append({"code": "embeddings_used", "message": "Reference tenant smoke must not use embeddings."})
    if checks["qdrant_used"]:
        errors.append({"code": "qdrant_used", "message": "Reference tenant smoke must not use Qdrant."})
    if checks["forbidden_warnings_present"]:
        errors.append(
            {
                "code": "forbidden_reference_tenant_warnings",
                "message": "Reference tenant still reports warnings that must be resolved.",
                "warnings": forbidden_warnings_present,
            }
        )
    if checks["search_index_contract_inconsistent"]:
        errors.append(
            {
                "code": "search_index_contract_inconsistent",
                "message": "Enterprise Search returned results without matching PostgreSQL Knowledge Index records.",
            }
        )

    required_positive = [
        "provision_passed",
        "validation_passed",
        "readiness_returned",
        "status_returned",
        "assets_returned",
        "organization_ready",
        "security_ready",
        "knowledge_ready",
        "documents_ready",
        "assistant_ready",
        "knowledge_source_ready",
        "feedback_ready",
        "audit_ready",
        "search_ready",
        "chat_ready",
        "reference_content_provisioned",
        "reference_documents_present",
        "knowledge_records_present",
        "knowledge_indexed",
        "enterprise_search_ready",
        "product_baseline_ready",
        "storage_reused_route_accepted",
        "postgresql_source_of_truth",
        "idempotency_verified",
    ]
    for key in required_positive:
        if not checks[key]:
            errors.append({"code": key, "message": f"{key} was not satisfied."})

    passed = not errors
    result = {
        "passed": passed,
        "api_base_url": API_BASE_URL,
        "provision_passed": provision_passed,
        "validation_passed": validation_passed,
        "readiness_returned": readiness_returned,
        "status_returned": status_returned,
        "assets_returned": assets_returned,
        "organization_ready": checks["organization_ready"],
        "security_ready": checks["security_ready"],
        "knowledge_ready": checks["knowledge_ready"],
        "documents_ready": checks["documents_ready"],
        "assistant_ready": checks["assistant_ready"],
        "knowledge_source_ready": checks["knowledge_source_ready"],
        "feedback_ready": checks["feedback_ready"],
        "audit_ready": checks["audit_ready"],
        "search_ready": checks["search_ready"],
        "chat_ready": checks["chat_ready"],
        "reference_content_provisioned": checks["reference_content_provisioned"],
        "reference_documents_count": reference_documents_count,
        "knowledge_records": knowledge_records,
        "knowledge_document_ids": knowledge_document_ids,
        "knowledge_chunk_count": knowledge_chunk_count,
        "knowledge_index_status": knowledge_index_status,
        "knowledge_index_blocking_issues": knowledge_index_blocking_issues,
        "knowledge_index_warnings": knowledge_index_warnings,
        "search_index_contract_inconsistent": search_index_contract_inconsistent,
        "knowledge_records_present": checks["knowledge_records_present"],
        "knowledge_indexed": checks["knowledge_indexed"],
        "enterprise_search_ready": checks["enterprise_search_ready"],
        "product_baseline_ready": checks["product_baseline_ready"],
        "storage_reused_route_accepted": checks["storage_reused_route_accepted"],
        "postgresql_source_of_truth": checks["postgresql_source_of_truth"],
        "idempotency_verified": idempotency_verified,
        "duplicate_assets_detected": duplicate_assets_detected,
        "duplicate_risks": duplicate_risks,
        "forbidden_warnings_present": forbidden_warnings_present,
        "llm_used": checks["llm_used"],
        "embeddings_used": checks["embeddings_used"],
        "qdrant_used": checks["qdrant_used"],
        "asset_counts_before_second_provision": counts_before_second,
        "asset_counts_after_second_provision": counts_after_second,
        "asset_counts": counts_after_second or counts_before_second,
        "lifecycle_diagnostics": [
            {
                "logical_key": item.get("logical_key"),
                "storage_reused": item.get("storage_reused"),
                "storage_reuse_status_complete": item.get("storage_reuse_status_complete"),
                "processing_handoff_ready": item.get("processing_handoff_ready"),
                "processing_handoff_blocking_issues": item.get("processing_handoff_blocking_issues") or [],
                "processing_completed": item.get("processing_completed"),
                "chunks_created": item.get("chunks_created"),
                "knowledge_published": item.get("knowledge_published"),
                "knowledge_indexed": item.get("knowledge_indexed"),
                "knowledge_document_id": item.get("knowledge_document_id"),
                "knowledge_document_ids": item.get("knowledge_document_ids") or [],
                "knowledge_chunk_count": item.get("knowledge_chunk_count") or item.get("knowledge_index_count"),
                "knowledge_index_status": item.get("knowledge_index_status"),
                "knowledge_index_blocking_issues": item.get("knowledge_index_blocking_issues") or [],
                "knowledge_index_warnings": item.get("knowledge_index_warnings") or [],
                "enterprise_search_ready": item.get("enterprise_search_ready"),
                "search_result_count": item.get("search_result_count"),
                "search_index_contract_inconsistent": item.get("search_index_contract_inconsistent"),
                "chat_ready": item.get("chat_ready"),
            }
            for item in lifecycle_diagnostics
        ],
        "domain_results": domain_results,
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
