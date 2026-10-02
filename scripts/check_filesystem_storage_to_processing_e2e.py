#!/usr/bin/env python3
"""Manual smoke contract for filesystem storage handoff into Processing Runtime."""

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

from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_filesystem import FilesystemStorageProvider  # noqa: E402


CONTENT_TEXT = "Industrial AI Platform filesystem-to-processing smoke payload.\nSecond line for parser validation."
CONTENT_TYPE = "text/plain"


def _upload_session(storage_root: Path) -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = FilesystemStorageProvider({"storage_root": str(storage_root)}).descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "filesystem-storage-processing-e2e-smoke",
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
        requested_by="filesystem-storage-processing-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"filesystem-storage-processing-e2e:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


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
    storage_root = Path(tempfile.mkdtemp(prefix="industrial-ai-storage-processing-fs-"))
    try:
        upload_session = _upload_session(storage_root)
        artifact_id = upload_session["artifact_id"]

        create_result = _request(upload_session, "create_object")
        object_handle = _object_handle(create_result)

        upload_result = _request(
            upload_session,
            "upload_object",
            metadata={
                "object_handle": object_handle,
                "content_text": CONTENT_TEXT,
                "content_type": CONTENT_TYPE,
                "metadata": {"source": "filesystem_storage_to_processing_e2e_smoke"},
            },
        )
        object_handle = _object_handle(upload_result) or object_handle

        verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
        handoff = build_document_processing_handoff(
            artifact_id=artifact_id,
            storage_execution_status=verify_result,
        )
        processing = build_document_processing_execution(handoff)
        processing_result = processing.get("processing_result") if isinstance(processing.get("processing_result"), dict) else {}
        parser_runtime = processing.get("parser_runtime") if isinstance(processing.get("parser_runtime"), dict) else {}
        source_summary = handoff.get("source_storage_summary") if isinstance(handoff.get("source_storage_summary"), dict) else {}

        storage_ok = all(
            (
                _expect(bool(verify_result.get("storage_verified")), failures, "storage verification must pass"),
                _expect(bool(verify_result.get("processing_handoff_prerequisite_met")), failures, "storage handoff prerequisite must pass"),
                _expect(verify_result.get("storage_provider_type") == "filesystem", failures, "storage provider must be filesystem"),
                _expect(object_handle is not None, failures, "storage must return object_handle"),
            )
        )
        handoff_ok = all(
            (
                _expect(bool(handoff.get("processing_handoff_ready")), failures, "processing handoff must be ready"),
                _expect(bool(handoff.get("processing_handoff_allowed")), failures, "processing handoff must be allowed"),
                _expect(source_summary.get("storage_provider_type") == "filesystem", failures, "handoff source provider must be filesystem"),
                _expect(bool(source_summary.get("object_handle")), failures, "handoff source must include object_handle"),
            )
        )
        processing_ok = all(
            (
                _expect(processing.get("processing_status") == "completed", failures, "processing status must be completed"),
                _expect(processing.get("processing_completed") is True, failures, "processing_completed must be true"),
                _expect(processing.get("processing_succeeded") is True, failures, "processing_succeeded must be true"),
                _expect(parser_runtime.get("parser_executed") is True, failures, "parser must execute"),
                _expect(processing_result.get("text_extracted") is True, failures, "text must be extracted"),
                _expect(processing_result.get("parsed_text") == CONTENT_TEXT, failures, "parsed_text must match filesystem payload"),
                _expect(processing_result.get("chunks_created") is False, failures, "chunks_created must remain false"),
                _expect(processing_result.get("embeddings_created") is False, failures, "embeddings_created must remain false"),
                _expect(processing.get("ai_required") is False, failures, "ai_required must remain false"),
            )
        )

        payload = {
            "passed": all((storage_ok, handoff_ok, processing_ok)) and not failures,
            "storage_verified": bool(verify_result.get("storage_verified")),
            "storage_provider_type": verify_result.get("storage_provider_type"),
            "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
            "processing_handoff_allowed": bool(handoff.get("processing_handoff_allowed")),
            "processing_completed": bool(processing.get("processing_completed")),
            "parser_executed": bool(parser_runtime.get("parser_executed")),
            "text_extracted": bool(processing_result.get("text_extracted")),
            "chunks_created": bool(processing_result.get("chunks_created")),
            "embeddings_created": bool(processing_result.get("embeddings_created")),
            "ai_required": bool(processing.get("ai_required")),
            "failures": failures,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["passed"] else 1
    finally:
        shutil.rmtree(storage_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
