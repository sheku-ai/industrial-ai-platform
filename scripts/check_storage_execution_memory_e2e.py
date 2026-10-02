#!/usr/bin/env python3
"""Manual smoke contract for in-memory storage execution gateway flow."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = "industrial-ai-platform memory storage smoke payload"
CONTENT_BYTES = CONTENT_TEXT.encode("utf-8")
CONTENT_TYPE = "text/plain"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "storage-memory-e2e-smoke",
        "runtime_state": "ready",
        "runtime_trace": {},
        "storage_provider_descriptor": provider_descriptor,
        "execution_flags": {
            "storage_provider_name": "memory",
            "storage_provider_type": "memory",
            "storage_provider_configured": True,
            "storage_provider_status": "configured",
            "object_stored": False,
            "file_uploaded": False,
            "checksum_calculated": False,
            "ingestion_executed": False,
            "chunks_created": False,
            "embeddings_created": False,
            "ai_required": False,
            "vector_store_required": False,
        },
    }


def _request(
    upload_session: dict[str, Any],
    operation: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_storage_execution_request(
        upload_session,
        requested_operation=operation,
        requested_by="storage-memory-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"storage-memory-e2e:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _result_descriptor(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("result_descriptor")
    return value if isinstance(value, dict) else {}


def _result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    execution_request = _execution_request(result)
    operation_result = execution_request.get("storage_operation_result")
    if not isinstance(operation_result, dict):
        return {}
    metadata = operation_result.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    execution_request = _execution_request(result)
    handle = execution_request.get("object_handle")
    return handle if isinstance(handle, dict) else None


def _expect(condition: bool, failures: list[str], message: str) -> bool:
    if condition:
        return True
    failures.append(message)
    return False


def _validate_create(result: dict[str, Any], failures: list[str]) -> bool:
    request = _execution_request(result)
    descriptor = _result_descriptor(result)
    checks = [
        _expect(request.get("operation_invoked") is True, failures, "CREATE operation_invoked must be true"),
        _expect(
            request.get("real_storage_operations_enabled") is True,
            failures,
            "CREATE real_storage_operations_enabled must be true",
        ),
        _expect(descriptor.get("object_exists") is True, failures, "CREATE object_exists must be true"),
        _expect(descriptor.get("object_stored") is False, failures, "CREATE object_stored must be false"),
        _expect(descriptor.get("file_uploaded") is False, failures, "CREATE file_uploaded must be false"),
        _expect(_object_handle(result) is not None, failures, "CREATE must return object_handle"),
    ]
    return all(checks)


def _validate_upload(result: dict[str, Any], failures: list[str]) -> bool:
    descriptor = _result_descriptor(result)
    checks = [
        _expect(descriptor.get("object_exists") is True, failures, "UPLOAD object_exists must be true"),
        _expect(descriptor.get("object_stored") is True, failures, "UPLOAD object_stored must be true"),
        _expect(descriptor.get("file_uploaded") is True, failures, "UPLOAD file_uploaded must be true"),
        _expect(descriptor.get("checksum_calculated") is True, failures, "UPLOAD checksum_calculated must be true"),
        _expect(bool(descriptor.get("checksum")), failures, "UPLOAD checksum must be present"),
        _expect(descriptor.get("content_length") == len(CONTENT_BYTES), failures, "UPLOAD content_length must match payload"),
        _expect(descriptor.get("content_type") == CONTENT_TYPE, failures, "UPLOAD content_type must match"),
    ]
    return all(checks)


def _validate_verify(result: dict[str, Any], failures: list[str]) -> bool:
    checks = [
        _expect(result.get("storage_verified") is True, failures, "VERIFY storage_verified must be true"),
        _expect(
            result.get("processing_handoff_prerequisite_met") is True,
            failures,
            "VERIFY processing_handoff_prerequisite_met must be true",
        ),
        _expect(
            result.get("prepared_execution", {}).get("processing_handoff_allowed") is False,
            failures,
            "VERIFY processing_handoff_allowed must remain false",
        ),
    ]
    return all(checks)


def _validate_head(result: dict[str, Any], failures: list[str]) -> bool:
    metadata = _result_metadata(result)
    checks = [
        _expect(_result_descriptor(result).get("object_exists") is True, failures, "HEAD object_exists must be true"),
        _expect("content" not in metadata, failures, "HEAD must not return content"),
    ]
    return all(checks)


def _validate_get(result: dict[str, Any], failures: list[str]) -> bool:
    metadata = _result_metadata(result)
    checks = [
        _expect(metadata.get("content_available") is True, failures, "GET content_available must be true"),
        _expect(metadata.get("content_returned") is False, failures, "GET content_returned must be false"),
        _expect("content" not in metadata, failures, "GET must not expose binary content"),
    ]
    return all(checks)


def _validate_delete(result: dict[str, Any], failures: list[str]) -> bool:
    request = _execution_request(result)
    metadata = _result_metadata(result)
    checks = [
        _expect(request.get("operation_invoked") is True, failures, "DELETE operation_invoked must be true"),
        _expect(_result_descriptor(result).get("object_exists") is False, failures, "DELETE object_exists must be false"),
        _expect(metadata.get("deleted") is True, failures, "DELETE deleted must be true"),
    ]
    return all(checks)


def main() -> int:
    failures: list[str] = []
    upload_session = _upload_session()

    create_result = _request(upload_session, "create_object")
    object_handle = _object_handle(create_result)

    upload_result = _request(
        upload_session,
        "upload_object",
        metadata={
            "object_handle": object_handle,
            "content_text": CONTENT_TEXT,
            "content_type": CONTENT_TYPE,
            "metadata": {"source": "storage_memory_e2e_smoke"},
        },
    )
    object_handle = _object_handle(upload_result) or object_handle

    verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
    head_result = _request(upload_session, "head_object", metadata={"object_handle": object_handle})
    get_result = _request(upload_session, "get_object", metadata={"object_handle": object_handle})
    delete_result = _request(upload_session, "delete_object", metadata={"object_handle": object_handle})

    create_ok = _validate_create(create_result, failures)
    upload_ok = _validate_upload(upload_result, failures)
    verify_ok = _validate_verify(verify_result, failures)
    head_ok = _validate_head(head_result, failures)
    get_ok = _validate_get(get_result, failures)
    delete_ok = _validate_delete(delete_result, failures)

    processing_handoff_allowed = bool(verify_result.get("prepared_execution", {}).get("processing_handoff_allowed"))
    payload = {
        "passed": all((create_ok, upload_ok, verify_ok, head_ok, get_ok, delete_ok)) and not failures,
        "create_ok": create_ok,
        "upload_ok": upload_ok,
        "verify_ok": verify_ok,
        "head_ok": head_ok,
        "get_ok": get_ok,
        "delete_ok": delete_ok,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_handoff_prerequisite_met": bool(verify_result.get("processing_handoff_prerequisite_met")),
        "processing_handoff_allowed": processing_handoff_allowed,
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
