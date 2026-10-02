#!/usr/bin/env python3
"""Manual smoke contract for durable filesystem storage execution flow."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_filesystem import FilesystemStorageProvider  # noqa: E402


CONTENT_TEXT = "industrial-ai-platform filesystem storage smoke payload"
CONTENT_BYTES = CONTENT_TEXT.encode("utf-8")
CONTENT_TYPE = "text/plain"


def _upload_session(storage_root: Path) -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = FilesystemStorageProvider({"storage_root": str(storage_root)}).descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "storage-filesystem-e2e-smoke",
        "runtime_state": "ready",
        "runtime_trace": {},
        "storage_provider_descriptor": provider_descriptor,
        "execution_flags": {
            "storage_provider_name": "filesystem",
            "storage_provider_type": "filesystem",
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
        requested_by="storage-filesystem-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"storage-filesystem-e2e:{operation}",
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


def main() -> int:
    failures: list[str] = []
    storage_root = Path(tempfile.mkdtemp(prefix="industrial-ai-storage-fs-"))
    try:
        upload_session = _upload_session(storage_root)

        create_result = _request(upload_session, "create_object")
        object_handle = _object_handle(create_result)

        upload_result = _request(
            upload_session,
            "upload_object",
            metadata={
                "object_handle": object_handle,
                "content_text": CONTENT_TEXT,
                "content_type": CONTENT_TYPE,
                "metadata": {"source": "storage_filesystem_e2e_smoke"},
            },
        )
        object_handle = _object_handle(upload_result) or object_handle

        verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
        head_result = _request(upload_session, "head_object", metadata={"object_handle": object_handle})
        get_result = _request(upload_session, "get_object", metadata={"object_handle": object_handle})
        delete_result = _request(upload_session, "delete_object", metadata={"object_handle": object_handle})
        delete_again_result = _request(upload_session, "delete_object", metadata={"object_handle": object_handle})

        create_descriptor = _result_descriptor(create_result)
        upload_descriptor = _result_descriptor(upload_result)
        head_metadata = _result_metadata(head_result)
        get_metadata = _result_metadata(get_result)
        delete_metadata = _result_metadata(delete_result)

        create_ok = all(
            (
                _expect(_execution_request(create_result).get("operation_invoked") is True, failures, "CREATE operation_invoked must be true"),
                _expect(create_descriptor.get("provider_type") == "filesystem", failures, "CREATE provider_type must be filesystem"),
                _expect(create_descriptor.get("object_exists") is True, failures, "CREATE object_exists must be true"),
                _expect(create_descriptor.get("object_stored") is False, failures, "CREATE object_stored must be false"),
                _expect(object_handle is not None, failures, "CREATE must return object_handle"),
            )
        )
        upload_ok = all(
            (
                _expect(upload_descriptor.get("object_exists") is True, failures, "UPLOAD object_exists must be true"),
                _expect(upload_descriptor.get("object_stored") is True, failures, "UPLOAD object_stored must be true"),
                _expect(upload_descriptor.get("file_uploaded") is True, failures, "UPLOAD file_uploaded must be true"),
                _expect(upload_descriptor.get("checksum_calculated") is True, failures, "UPLOAD checksum_calculated must be true"),
                _expect(bool(upload_descriptor.get("checksum")), failures, "UPLOAD checksum must be present"),
                _expect(upload_descriptor.get("content_length") == len(CONTENT_BYTES), failures, "UPLOAD content_length must match payload"),
                _expect(upload_descriptor.get("content_type") == CONTENT_TYPE, failures, "UPLOAD content_type must match"),
            )
        )
        verify_ok = all(
            (
                _expect(verify_result.get("storage_verified") is True, failures, "VERIFY storage_verified must be true"),
                _expect(verify_result.get("processing_handoff_prerequisite_met") is True, failures, "VERIFY processing handoff prerequisite must be true"),
                _expect(verify_result.get("storage_provider_type") == "filesystem", failures, "VERIFY provider_type must be filesystem"),
            )
        )
        head_ok = all(
            (
                _expect(_result_descriptor(head_result).get("object_exists") is True, failures, "HEAD object_exists must be true"),
                _expect("content" not in head_metadata, failures, "HEAD must not return content"),
            )
        )
        get_ok = all(
            (
                _expect(get_metadata.get("content_available") is True, failures, "GET content_available must be true"),
                _expect(get_metadata.get("content_returned") is False, failures, "GET content_returned must be false"),
                _expect("content" not in get_metadata, failures, "GET must not expose binary content"),
            )
        )
        delete_ok = all(
            (
                _expect(_execution_request(delete_result).get("operation_invoked") is True, failures, "DELETE operation_invoked must be true"),
                _expect(_result_descriptor(delete_result).get("object_exists") is False, failures, "DELETE object_exists must be false"),
                _expect(delete_metadata.get("deleted") is True, failures, "DELETE deleted must be true"),
                _expect(_execution_request(delete_again_result).get("operation_invoked") is True, failures, "DELETE idempotent call must be invoked"),
            )
        )

        payload = {
            "passed": all((create_ok, upload_ok, verify_ok, head_ok, get_ok, delete_ok)) and not failures,
            "create_ok": create_ok,
            "upload_ok": upload_ok,
            "verify_ok": verify_ok,
            "head_ok": head_ok,
            "get_ok": get_ok,
            "delete_ok": delete_ok,
            "storage_verified": bool(verify_result.get("storage_verified")),
            "storage_provider_type": verify_result.get("storage_provider_type"),
            "processing_handoff_prerequisite_met": bool(verify_result.get("processing_handoff_prerequisite_met")),
            "failures": failures,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["passed"] else 1
    finally:
        shutil.rmtree(storage_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
