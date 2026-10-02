#!/usr/bin/env python3
"""Manual smoke contract for Runtime Persistence Foundation."""

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

from app.db.session import SessionLocal  # noqa: E402
from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.enterprise_search_runtime import build_enterprise_search  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import persist_runtime_outputs, read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Industrial AI Platform persists storage, processing, chunking, publication and search runtime state.\n"
    "Runtime persistence stores citation-ready enterprise search results without embeddings or AI.\n\n"
    "The persisted records can be read back from PostgreSQL as the source of truth."
)
CONTENT_TYPE = "text/plain"
QUERY = "runtime persistence search results"


def _upload_session() -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "runtime-persistence-e2e-smoke",
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
        requested_by="runtime-persistence-e2e-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"runtime-persistence-e2e:{operation}",
    )


def _execution_request(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict[str, Any]) -> dict[str, Any] | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _records(readback: dict[str, Any], domain: str, record_type: str | None = None) -> list[dict[str, Any]]:
    records = [item for item in readback.get("records") or [] if item.get("runtime_domain") == domain]
    if record_type is not None:
        records = [item for item in records if item.get("record_type") == record_type]
    return records


def _expect(condition: bool, failures: list[str], message: str) -> bool:
    if condition:
        return True
    failures.append(message)
    return False


def main() -> int:
    failures: list[str] = []
    if SessionLocal is None:
        payload = {"passed": False, "failures": ["database url is not configured"]}
        print(json.dumps(payload, sort_keys=True))
        return 1

    upload_session = _upload_session()
    artifact_id = upload_session["artifact_id"]
    execution_id = f"runtime-persistence-e2e:{artifact_id}"

    create_result = _request(upload_session, "create_object")
    object_handle = _object_handle(create_result)

    upload_result = _request(
        upload_session,
        "upload_object",
        metadata={
            "object_handle": object_handle,
            "content_text": CONTENT_TEXT,
            "content_type": CONTENT_TYPE,
            "metadata": {"source": "runtime_persistence_e2e_smoke"},
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

    db = SessionLocal()
    try:
        knowledge_index = build_knowledge_index(db, publication)
        search = build_enterprise_search(db=db, query=QUERY, top_k=5)
        runtime_outputs = {
            "storage": [create_result, upload_result, verify_result],
            "processing": processing,
            "chunk": chunk_generation,
            "knowledge_publication": publication,
            "knowledge_index": knowledge_index,
            "enterprise_search": search,
        }
        persistence = persist_runtime_outputs(
            db,
            execution_id=execution_id,
            artifact_id=artifact_id,
            runtime_outputs=runtime_outputs,
        )
        readback = read_runtime_persistence(db, execution_id=execution_id)
    finally:
        db.close()

    storage_ok = bool(verify_result.get("storage_verified"))
    processing_ok = all((processing.get("processing_completed") is True, parser_runtime.get("parser_executed") is True))
    chunk_ok = all((chunk_generation.get("chunk_generation_completed") is True, chunk_generation.get("chunks_created") is True))
    publication_ok = all((publication.get("publication_completed") is True, publication.get("knowledge_published") is True))
    index_ok = all(
        (
            knowledge_index.get("index_completed") is True,
            knowledge_index.get("document_indexed") is True,
            knowledge_index.get("chunks_indexed") == publication.get("published_chunk_count"),
            knowledge_index.get("metadata_persisted") is True,
        )
    )
    search_ok = all((search.get("search_completed") is True, search.get("search_succeeded") is True, int(search.get("result_count") or 0) >= 1))
    persistence_ok = all(
        (
            persistence.get("persistence_completed") is True,
            persistence.get("persistence_succeeded") is True,
            int(persistence.get("records_persisted") or 0) >= 10,
            readback.get("persistence_status") == "persisted",
            readback.get("record_count") == persistence.get("records_persisted"),
        )
    )
    domain_ok = all(
        (
            len(_records(readback, "storage", "execution_request")) >= 1,
            len(_records(readback, "storage", "execution_result")) >= 1,
            len(_records(readback, "storage", "verification_result")) >= 1,
            len(_records(readback, "processing", "processing_result")) == 1,
            len(_records(readback, "chunk", "chunk")) == int(chunk_generation.get("chunk_count") or 0),
            len(_records(readback, "knowledge_publication", "published_chunk")) == int(publication.get("published_chunk_count") or 0),
            len(_records(readback, "knowledge_index", "knowledge_document")) == 1,
            len(_records(readback, "knowledge_index", "knowledge_chunk")) == int(knowledge_index.get("chunks_indexed") or 0),
            len(_records(readback, "enterprise_search", "search_result")) == int(search.get("result_count") or 0),
            len(_records(readback, "enterprise_search", "citation")) == len(search.get("citations") or []),
        )
    )
    consistency_ok = all(
        (
            (_records(readback, "processing", "processing_result")[0].get("summary") or {}).get("text_extracted") is True,
            (_records(readback, "knowledge_publication", "publication_result")[0].get("summary") or {}).get("knowledge_published") is True,
            (_records(readback, "knowledge_index", "index_result")[0].get("summary") or {}).get("index_succeeded") is True,
            (_records(readback, "enterprise_search", "search_result_set")[0].get("summary") or {}).get("result_count") == search.get("result_count"),
        )
    ) if domain_ok else False

    _expect(storage_ok, failures, "storage runtime must verify object")
    _expect(processing_ok, failures, "processing runtime must complete")
    _expect(chunk_ok, failures, "chunk runtime must create chunks")
    _expect(publication_ok, failures, "knowledge publication runtime must publish chunks")
    _expect(index_ok, failures, "knowledge index runtime must persist published chunks")
    _expect(search_ok, failures, "enterprise search runtime must return results")
    _expect(persistence_ok, failures, "runtime persistence must persist and read records")
    _expect(domain_ok, failures, "all runtime domains must have persisted records")
    _expect(consistency_ok, failures, "readback records must be consistent with generated runtime outputs")

    payload = {
        "passed": all((storage_ok, processing_ok, chunk_ok, publication_ok, index_ok, search_ok, persistence_ok, domain_ok, consistency_ok)) and not failures,
        "execution_id": execution_id,
        "storage_verified": bool(verify_result.get("storage_verified")),
        "processing_completed": bool(processing.get("processing_completed")),
        "parser_executed": bool(parser_runtime.get("parser_executed")),
        "chunk_generation_completed": bool(chunk_generation.get("chunk_generation_completed")),
        "chunks_created": bool(chunk_generation.get("chunks_created")),
        "publication_completed": bool(publication.get("publication_completed")),
        "knowledge_published": bool(publication.get("knowledge_published")),
        "index_completed": bool(knowledge_index.get("index_completed")),
        "document_indexed": bool(knowledge_index.get("document_indexed")),
        "chunks_indexed": knowledge_index.get("chunks_indexed"),
        "metadata_persisted": bool(knowledge_index.get("metadata_persisted")),
        "search_completed": bool(search.get("search_completed")),
        "search_succeeded": bool(search.get("search_succeeded")),
        "persistence_completed": bool(persistence.get("persistence_completed")),
        "persistence_succeeded": bool(persistence.get("persistence_succeeded")),
        "records_persisted": persistence.get("records_persisted"),
        "readback_record_count": readback.get("record_count"),
        "domains": readback.get("domains"),
        "failures": failures,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
