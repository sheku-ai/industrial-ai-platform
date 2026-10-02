"""Manual E2E smoke for Document Lifecycle Orchestrator over the public API."""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import error, request
from urllib.parse import quote

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ORGANIZATION_ID = os.environ.get("SMOKE_ORGANIZATION_ID")
DOCUMENT_TYPE_ID = os.environ.get("SMOKE_DOCUMENT_TYPE_ID")
FILE_NAME = os.environ.get("SMOKE_FILE_NAME", "document-lifecycle-smoke.txt")
FILE_CONTENT = os.environ.get(
    "SMOKE_FILE_CONTENT",
    "\n\n".join(
        [
            "Industrial AI lifecycle smoke document.",
            "The orchestrator registers, uploads, verifies, processes, publishes and indexes this text.",
            "Enterprise Search should find lifecycle smoke document after PostgreSQL indexing.",
        ]
    ),
)
REQUESTED_BY = os.environ.get("SMOKE_REQUESTED_BY", "smoke")
STORAGE_PROVIDER = os.environ.get("SMOKE_STORAGE_PROVIDER", "filesystem")
STORAGE_ROOT = os.environ.get("SMOKE_STORAGE_ROOT", "/tmp/industrial-ai-platform/runtime/storage/filesystem")
ACTOR_REFERENCE = os.environ.get("SMOKE_ACTOR_REFERENCE", "reference-administrator")
PRINCIPAL_TYPE = os.environ.get("SMOKE_PRINCIPAL_TYPE", "reference_principal")
REQUEST_ORGANIZATION_ID: str | None = ORGANIZATION_ID


class SmokeHttpError(RuntimeError):
    def __init__(self, method: str, path: str, status_code: int | None, detail: Any) -> None:
        super().__init__(f"{method} {path} failed")
        self.method = method
        self.path = path
        self.status_code = status_code
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "detail": self.detail,
        }


def _read_error_detail(exc: error.HTTPError) -> Any:
    raw = exc.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _http_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Content-Type": "application/json",
        "X-Authorization-Scope": "organization" if REQUEST_ORGANIZATION_ID else "platform",
        "X-Actor-Reference": ACTOR_REFERENCE,
        "X-Principal-Type": PRINCIPAL_TYPE,
    }
    if REQUEST_ORGANIZATION_ID:
        headers["X-Organization-ID"] = REQUEST_ORGANIZATION_ID
    req = request.Request(
        f"{API_BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raise SmokeHttpError(method, path, exc.code, _read_error_detail(exc)) from exc
    except error.URLError as exc:
        raise SmokeHttpError(method, path, None, str(exc.reason)) from exc


def http_get_json(path: str) -> Any:
    return _http_json("GET", path)


def http_post_json(path: str, payload: dict[str, Any]) -> Any:
    return _http_json("POST", path, payload)


def extract_id(value: Any, *keys: str) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in (*keys, "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _first_id(items: Any, *keys: str) -> str | None:
    if isinstance(items, list):
        for item in items:
            resolved = extract_id(item, *keys)
            if resolved:
                return resolved
    if isinstance(items, dict):
        for list_key in ("items", "results", "data"):
            resolved = _first_id(items.get(list_key), *keys)
            if resolved:
                return resolved
    return None


def _failure(
    error_code: str, details: Any, *, warnings: list[Any] | None = None, errors: list[Any] | None = None
) -> dict[str, Any]:
    return {
        "passed": False,
        "organization_id": ORGANIZATION_ID,
        "document_type_id": DOCUMENT_TYPE_ID,
        "runtime_id": None,
        "document_record_id": None,
        "document_version_id": None,
        "processing_job_id": None,
        "processing_revision_id": None,
        "worker_required": None,
        "knowledge_publication_pending": None,
        "enterprise_search_pending": None,
        "chat_ready": False,
        "warnings": warnings or [],
        "errors": [*(errors or []), {"error": error_code, "details": details}],
        "error": error_code,
        "details": details,
    }


def resolve_first_or_create_organization() -> tuple[str | None, list[Any], dict[str, Any] | None]:
    if ORGANIZATION_ID:
        return ORGANIZATION_ID, [], None
    try:
        existing = http_get_json("/core/organizations")
        if isinstance(existing, list):
            reference = next(
                (item for item in existing if isinstance(item, dict) and item.get("slug") == "reference-tenant"),
                None,
            )
            resolved = extract_id(reference, "organization_id")
            if resolved:
                return resolved, [], None
        resolved = _first_id(existing, "organization_id")
        if resolved:
            return resolved, [], None
    except SmokeHttpError as exc:
        return None, [], _failure("unable_to_resolve_organization", exc.as_dict())

    payload = {
        "slug": f"smoke-org-{uuid.uuid4().hex[:12]}",
        "name": "Smoke Organization",
        "description": "Autocreated by document lifecycle smoke.",
        "status": "active",
        "config": {"smoke": True},
    }
    try:
        created = http_post_json("/core/organizations", payload)
        resolved = extract_id(created, "organization_id")
        if resolved:
            return resolved, [{"organization_created": True, "organization_id": resolved}], None
        return None, [], _failure("unable_to_resolve_organization", {"payload": payload, "response": created})
    except SmokeHttpError as exc:
        return None, [], _failure("unable_to_resolve_organization", {"payload": payload, "http_error": exc.as_dict()})


def resolve_first_or_create_document_type(organization_id: str) -> tuple[str | None, list[Any], dict[str, Any] | None]:
    if DOCUMENT_TYPE_ID:
        return DOCUMENT_TYPE_ID, [], None
    try:
        existing = http_get_json("/documents/document-types")
        resolved = _first_id(existing, "document_type_id")
        if resolved:
            return resolved, [], None
    except SmokeHttpError as exc:
        return None, [], _failure("unable_to_resolve_document_type", exc.as_dict())

    payload = {
        "organization_id": organization_id,
        "code": f"smoke_document_type_{uuid.uuid4().hex[:12]}",
        "name": "Smoke Document Type",
        "description": "Autocreated by document lifecycle smoke.",
        "version": "1.0",
        "status": "active",
        "config": {"smoke": True},
    }
    try:
        created = http_post_json("/documents/document-types", payload)
        resolved = extract_id(created, "document_type_id")
        if resolved:
            return resolved, [{"document_type_created": True, "document_type_id": resolved}], None
        return None, [], _failure("unable_to_resolve_document_type", {"payload": payload, "response": created})
    except SmokeHttpError as exc:
        return None, [], _failure("unable_to_resolve_document_type", {"payload": payload, "http_error": exc.as_dict()})


def _nested_get(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _runtime_id(result: dict[str, Any]) -> str | None:
    return (
        extract_id(
            result.get("runtime_persistence") if isinstance(result.get("runtime_persistence"), dict) else {},
            "execution_id",
        )
        or extract_id(result.get("idempotency") if isinstance(result.get("idempotency"), dict) else {}, "key")
        or result.get("artifact_id")
    )


def _processing_job_id(result: dict[str, Any]) -> str | None:
    return _nested_get(
        result, "stages", "processing_publication_search", "processing_execution", "processing_job_id"
    ) or _nested_get(result, "stages", "processing_publication_search", "processing_result", "processing_job_id")


def _processing_revision_id(result: dict[str, Any]) -> str | None:
    return _nested_get(
        result, "stages", "processing_publication_search", "processing_execution", "processing_revision_id"
    ) or _nested_get(result, "stages", "processing_publication_search", "processing_result", "processing_revision_id")


def _storage_field(result: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = result.get(key)
        if value is not None:
            return value
    persisted = _nested_get(result, "stages", "storage_state_persistence")
    if isinstance(persisted, dict):
        for key in keys:
            value = persisted.get(key)
            if value is not None:
                return value
    verification = _nested_get(result, "stages", "storage_verification")
    if isinstance(verification, dict):
        for key in keys:
            value = verification.get(key)
            if value is not None:
                return value
        result_descriptor = verification.get("result_descriptor")
        if isinstance(result_descriptor, dict):
            for key in keys:
                value = result_descriptor.get(key)
                if value is not None:
                    return value
    return None


def _collect_warnings(*payloads: Any) -> list[Any]:
    warnings: list[Any] = []
    for payload in payloads:
        if isinstance(payload, dict):
            warnings.extend(payload.get("warnings") or [])
    return warnings


def _readiness_warnings(organization_id: str) -> list[Any]:
    try:
        readiness = http_get_json(f"/documents/configuration/validation?organization_id={quote(organization_id)}")
    except SmokeHttpError as exc:
        return [{"readiness_check": "skipped", "reason": exc.as_dict()}]
    if isinstance(readiness, dict):
        issues = readiness.get("issues")
        if isinstance(issues, list) and issues:
            return [{"readiness_check": "documents.configuration.validation", "issues": issues}]
    return []


def main() -> int:
    global REQUEST_ORGANIZATION_ID

    warnings: list[Any] = []
    errors: list[Any] = []
    organization_id, org_warnings, org_failure = resolve_first_or_create_organization()
    warnings.extend(org_warnings)
    if org_failure:
        print(json.dumps(org_failure, indent=2, sort_keys=True))
        return 1
    if not organization_id:
        result = _failure("unable_to_resolve_organization", "organization id was empty", warnings=warnings)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    REQUEST_ORGANIZATION_ID = organization_id

    document_type_id, doc_type_warnings, doc_type_failure = resolve_first_or_create_document_type(organization_id)
    warnings.extend(doc_type_warnings)
    if doc_type_failure:
        doc_type_failure["organization_id"] = organization_id
        print(json.dumps(doc_type_failure, indent=2, sort_keys=True))
        return 1
    if not document_type_id:
        result = _failure("unable_to_resolve_document_type", "document type id was empty", warnings=warnings)
        result["organization_id"] = organization_id
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    warnings.extend(_readiness_warnings(organization_id))

    lifecycle_key = f"smoke-document-lifecycle:{uuid.uuid4()}"
    payload = {
        "registration": {
            "organization_id": organization_id,
            "title": "Document Lifecycle Orchestrator Smoke",
            "source_type": "manual_smoke",
            "document_type_id": document_type_id,
            "external_reference": lifecycle_key,
            "source_ref": {"smoke": "document_lifecycle_orchestrator"},
            "metadata": {"smoke": True},
            "classification": {},
            "requested_by": REQUESTED_BY,
        },
        "version_label": "smoke-v1",
        "file_name": FILE_NAME,
        "content_type": "text/plain",
        "content_text": FILE_CONTENT,
        "storage_provider": {
            "provider_name": STORAGE_PROVIDER,
            "provider_type": STORAGE_PROVIDER,
            "storage_root": STORAGE_ROOT,
        },
        "search_query": "lifecycle smoke document",
        "top_k": 5,
        "requested_by": REQUESTED_BY,
        "idempotency_key": lifecycle_key,
        "lifecycle_metadata": {"smoke": "document_lifecycle_orchestrator_e2e"},
    }
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(
                pool.map(
                    lambda _: http_post_json("/documents/lifecycle/orchestrate", payload),
                    range(2),
                )
            )
        result = concurrent_results[0]
        duplicate_result = concurrent_results[1]
    except SmokeHttpError as exc:
        final = _failure("document_lifecycle_orchestrate_failed", exc.as_dict(), warnings=warnings, errors=errors)
        final["organization_id"] = organization_id
        final["document_type_id"] = document_type_id
        print(json.dumps(final, indent=2, sort_keys=True))
        return 1

    if not isinstance(result, dict):
        final = _failure("document_lifecycle_response_invalid", result, warnings=warnings, errors=errors)
        final["organization_id"] = organization_id
        final["document_type_id"] = document_type_id
        print(json.dumps(final, indent=2, sort_keys=True))
        return 1
    duplicate_reused = bool(
        isinstance(duplicate_result, dict)
        and duplicate_result.get("document_record_id") == result.get("document_record_id")
        and duplicate_result.get("document_version_id") == result.get("document_version_id")
        and _storage_field(duplicate_result, "object_store_key", "object_key")
        == _storage_field(result, "object_store_key", "object_key")
    )
    if not duplicate_reused:
        errors.append({"error": "concurrent_lifecycle_not_reused"})

    warnings.extend(_collect_warnings(result))
    errors.extend(result.get("blocking_issues") or [])
    chat_ready = bool(result.get("chat_ready") or result.get("assistant_chat_available"))
    upload_executed = bool(result.get("upload_executed"))
    binary_attached = bool(result.get("binary_attached"))
    file_uploaded = bool(result.get("file_uploaded"))
    worker_required = bool(result.get("worker_required"))
    worker_execution_pending = bool(result.get("worker_execution_pending"))
    knowledge_publication_pending = bool(result.get("knowledge_publication_pending")) or not bool(
        result.get("knowledge_published")
    )
    enterprise_search_pending = bool(result.get("enterprise_search_pending")) or not bool(
        result.get("enterprise_search_visible")
    )
    object_store_key = _storage_field(result, "object_store_key", "object_key")
    checksum_sha256 = _storage_field(result, "checksum_sha256", "checksum")
    size_bytes = _storage_field(result, "size_bytes", "content_length")
    storage_metadata_complete = (
        bool(object_store_key) and bool(checksum_sha256) and isinstance(size_bytes, int) and size_bytes > 0
    )
    storage_execution_attempted = bool(result.get("storage_execution_attempted"))
    create_object_attempted = bool(result.get("create_object_attempted"))
    upload_object_attempted = bool(result.get("upload_object_attempted"))
    verify_object_attempted = bool(result.get("verify_object_attempted"))
    if bool(result.get("storage_verified")) and not storage_metadata_complete:
        errors.append(
            {
                "error": "storage_metadata_incomplete",
                "details": {
                    "object_store_key": object_store_key,
                    "checksum_sha256": checksum_sha256,
                    "size_bytes": size_bytes,
                },
            }
        )
    completed = (
        bool(result.get("lifecycle_completed"))
        and chat_ready
        and not knowledge_publication_pending
        and not enterprise_search_pending
    )
    prepared = (
        bool(result.get("orchestration_prepared") or result.get("storage_verified"))
        and bool(result.get("storage_verified"))
        and upload_executed
        and binary_attached
        and file_uploaded
        and storage_metadata_complete
        and storage_execution_attempted
        and create_object_attempted
        and upload_object_attempted
        and verify_object_attempted
        and worker_required
        and worker_execution_pending
        and not chat_ready
    )
    passed = completed or prepared
    final = {
        "passed": passed,
        "organization_id": organization_id,
        "document_type_id": document_type_id,
        "runtime_id": _runtime_id(result),
        "document_record_id": result.get("document_record_id"),
        "document_version_id": result.get("document_version_id"),
        "processing_job_id": _processing_job_id(result),
        "processing_revision_id": _processing_revision_id(result),
        "object_store_key": object_store_key,
        "checksum_sha256": checksum_sha256,
        "size_bytes": size_bytes,
        "upload_executed": upload_executed,
        "binary_attached": binary_attached,
        "file_uploaded": file_uploaded,
        "storage_verified": bool(result.get("storage_verified")),
        "storage_execution_attempted": storage_execution_attempted,
        "create_object_attempted": create_object_attempted,
        "upload_object_attempted": upload_object_attempted,
        "verify_object_attempted": verify_object_attempted,
        "worker_required": worker_required,
        "worker_execution_pending": worker_execution_pending,
        "knowledge_publication_pending": knowledge_publication_pending,
        "enterprise_search_pending": enterprise_search_pending,
        "chat_ready": chat_ready,
        "concurrent_upload_and_publication_reused": duplicate_reused,
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(final, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
