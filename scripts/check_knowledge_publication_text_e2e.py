#!/usr/bin/env python3
"""Manual smoke contract for Knowledge Publication Runtime text/plain execution."""

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

from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Industrial AI Platform knowledge publication smoke payload.\n"
    "Second line for parser validation.\n\n"
    "A second paragraph confirms publication of deterministic chunks."
)
CONTENT_TYPE = "text/plain"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "knowledge-publication-e2e-smoke",
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
        requested_by="knowledge-publication-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"knowledge-publication-e2e:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _expect(condition: bool, failures: list[str], message: str) -> bool:
    if condition:
        return True
    failures.append(message)
    return False


def main() -> int:
    failures: list[str] = []
    upload_session = _upload_session()
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
            "metadata": {"source": "knowledge_publication_e2e_smoke"},
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
    chunk_generation = build_document_chunk_generation(processing_result)
    chunk_result = chunk_generation.get("chunk_result") if isinstance(chunk_generation.get("chunk_result"), dict) else chunk_generation
    publication = build_knowledge_publication(chunk_result)
    published_chunks = publication.get("published_chunks") if isinstance(publication.get("published_chunks"), list) else []

    storage_ok = all(
        (
            bool(verify_result.get("storage_verified")),
            bool(verify_result.get("processing_handoff_prerequisite_met")),
            object_handle is not None,
        )
    )
    handoff_ok = all(
        (
            bool(handoff.get("processing_handoff_ready")),
            bool(handoff.get("processing_handoff_allowed")),
            bool((handoff.get("source_storage_summary") or {}).get("object_handle")),
        )
    )
    processing_ok = all(
        (
            processing.get("processing_status") == "completed",
            processing.get("processing_completed") is True,
            processing_result.get("processing_completed") is True,
            parser_runtime.get("parser_executed") is True,
            processing_result.get("parser_executed") is True,
            processing_result.get("text_extracted") is True,
        )
    )
    chunk_count = int(chunk_generation.get("chunk_count") or 0)
    chunk_ok = all(
        (
            chunk_generation.get("chunk_status") == "completed",
            chunk_generation.get("chunk_generation_completed") is True,
            chunk_generation.get("chunks_created") is True,
            chunk_count >= 1,
        )
    )
    publication_ok = all(
        (
            publication.get("publication_status") == "completed",
            publication.get("publication_completed") is True,
            publication.get("publication_succeeded") is True,
            publication.get("knowledge_published") is True,
            publication.get("published_chunk_count") == chunk_count,
            all(bool(chunk.get("published_chunk_id")) for chunk in published_chunks),
            all(bool(chunk.get("publication_id")) for chunk in published_chunks),
            all(isinstance(chunk.get("chunk_index"), int) for chunk in published_chunks),
            all(bool(chunk.get("content_hash")) for chunk in published_chunks),
            all(bool(chunk.get("semantic_hash")) for chunk in published_chunks),
            publication.get("embeddings_created") is False,
            publication.get("semantic_index_created") is False,
            publication.get("ai_required") is False,
        )
    )

    _expect(storage_ok, failures, "storage verification must pass before processing")
    _expect(handoff_ok, failures, "processing handoff must become ready and executable")
    _expect(processing_ok, failures, "processing runtime must parse text/plain payload")
    _expect(chunk_ok, failures, "chunk runtime must generate chunks before publication")
    _expect(publication_ok, failures, "knowledge publication runtime must publish chunks without semantic or AI execution")

    payload = {
        "passed": all((storage_ok, handoff_ok, processing_ok, chunk_ok, publication_ok)) and not failures,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_handoff_ready": bool(handoff.get("processing_handoff_ready")),
        "processing_completed": bool(processing.get("processing_completed")),
        "parser_executed": bool(parser_runtime.get("parser_executed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "chunks_created": bool(chunk_generation.get("chunks_created")),
        "chunk_count": chunk_generation.get("chunk_count"),
        "publication_completed": bool(publication.get("publication_completed")),
        "publication_succeeded": bool(publication.get("publication_succeeded")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "published_chunk_count": publication.get("published_chunk_count"),
        "all_published_chunks_have_published_chunk_id": all(bool(chunk.get("published_chunk_id")) for chunk in published_chunks),
        "all_published_chunks_have_publication_id": all(bool(chunk.get("publication_id")) for chunk in published_chunks),
        "all_published_chunks_have_chunk_index": all(isinstance(chunk.get("chunk_index"), int) for chunk in published_chunks),
        "all_published_chunks_have_content_hash": all(bool(chunk.get("content_hash")) for chunk in published_chunks),
        "all_published_chunks_have_semantic_hash": all(bool(chunk.get("semantic_hash")) for chunk in published_chunks),
        "embeddings_created": bool(publication.get("embeddings_created")),
        "semantic_index_created": bool(publication.get("semantic_index_created")),
        "ai_required": bool(publication.get("ai_required")),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
