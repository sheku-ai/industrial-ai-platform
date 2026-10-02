#!/usr/bin/env python3
"""Manual smoke contract for Assistant Enterprise Search Execution Runtime."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.services.assistant_retrieval_execution_runtime import build_assistant_retrieval_execution_readiness_runtime  # noqa: E402
from app.services.assistant_retrieval_runtime import build_assistant_retrieval_runtime  # noqa: E402
from app.services.assistant_runtime import build_assistant_runtime  # noqa: E402
from app.services.assistant_search_execution_runtime import build_assistant_search_execution_runtime  # noqa: E402
from app.services.document_chunk_runtime import build_document_chunk_generation  # noqa: E402
from app.services.document_processing_handoff import build_document_processing_handoff  # noqa: E402
from app.services.document_processing_runtime import build_document_processing_execution  # noqa: E402
from app.services.knowledge_index_runtime import build_knowledge_index  # noqa: E402
from app.services.knowledge_publication_runtime import build_knowledge_publication  # noqa: E402
from app.services.runtime_persistence_runtime import read_runtime_persistence  # noqa: E402
from app.services.storage_execution_gateway import build_storage_execution_request  # noqa: E402
from app.services.storage_provider_memory import InMemoryStorageProvider  # noqa: E402


CONTENT_TEXT = (
    "Assistant enterprise search execution uses PostgreSQL full text search only.\n"
    "The assistant retrieval chain executes lexical search and returns search results without LLMs.\n\n"
    "Semantic search, hybrid search, Qdrant, reranking, tools and workflows remain disabled."
)
CONTENT_TYPE = "text/plain"
QUERY = "assistant enterprise search lexical results"


def _upload_session() -> dict:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "assistant-search-execution-smoke",
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


def _request(upload_session: dict, operation: str, *, metadata: dict | None = None) -> dict:
    return build_storage_execution_request(
        upload_session,
        requested_operation=operation,
        requested_by="assistant-search-execution-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"assistant-search-execution:{operation}:{upload_session['artifact_id']}",
    )


def _execution_request(result: dict) -> dict:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict) -> dict | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


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
    create_result = _request(upload_session, "create_object")
    object_handle = _object_handle(create_result)
    upload_result = _request(
        upload_session,
        "upload_object",
        metadata={
            "object_handle": object_handle,
            "content_text": CONTENT_TEXT,
            "content_type": CONTENT_TYPE,
            "metadata": {"source": "assistant_search_execution_smoke"},
        },
    )
    object_handle = _object_handle(upload_result) or object_handle
    verify_result = _request(upload_session, "verify_object", metadata={"object_handle": object_handle})
    handoff = build_document_processing_handoff(artifact_id=artifact_id, storage_execution_status=verify_result)
    processing = build_document_processing_execution(handoff)
    processing_result = processing.get("processing_result") if isinstance(processing.get("processing_result"), dict) else {}
    chunk_generation = build_document_chunk_generation(processing_result)
    chunk_result = chunk_generation.get("chunk_result") if isinstance(chunk_generation.get("chunk_result"), dict) else chunk_generation
    publication = build_knowledge_publication(chunk_result)

    assistant_key = f"assistant-search-execution-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        knowledge_index = build_knowledge_index(db, publication)
        assistant_runtime = build_assistant_runtime(
            db,
            organization_id=None,
            ownership_scope="global",
            data_origin="validation",
            assistant_name="Assistant Search Execution Smoke",
            assistant_key=assistant_key,
            assistant_version="1.0",
            assistant_type="platform_assistant",
            description="Assistant enterprise search execution smoke.",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search", "hybrid_search_runtime", "semantic_search_runtime", "workflow_runtime"],
            requested_by="assistant-search-execution-e2e-smoke",
            conversation_reference=f"conversation:{assistant_key}",
            requested_query=QUERY,
            persist_snapshot=False,
        )
        retrieval_runtime = build_assistant_retrieval_runtime(
            db,
            assistant_id=assistant_runtime.get("assistant_id"),
            assistant_session_id=assistant_runtime.get("assistant_session_id"),
            requested_query=QUERY,
            selected_search_mode="enterprise_search",
            persist_snapshot=False,
        )
        readiness_runtime = build_assistant_retrieval_execution_readiness_runtime(
            db,
            retrieval_plan_id=retrieval_runtime.get("retrieval_plan_id"),
            persist_snapshot=False,
        )
        search_runtime = build_assistant_search_execution_runtime(
            db,
            execution_plan_id=readiness_runtime.get("execution_plan_id"),
            top_k=10,
            search_config={"artifact_id": artifact_id, "content_type": CONTENT_TYPE},
        )
        persistence_execution_id = (search_runtime.get("runtime_persistence") or {}).get("execution_id") if search_runtime else None
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    search_runtime = search_runtime or {}
    observed = {
        "assistant_search_execution_prepared": search_runtime.get("assistant_search_execution_prepared") is True,
        "retrieval_plan_created": search_runtime.get("retrieval_plan_created") is True,
        "execution_readiness_created": search_runtime.get("execution_readiness_created") is True,
        "enterprise_search_executed": search_runtime.get("enterprise_search_executed") is True,
        "postgresql_fts_used": search_runtime.get("postgresql_fts_used") is True,
        "lexical_search_used": search_runtime.get("lexical_search_used") is True,
        "result_count_gt_zero": search_runtime.get("result_count_gt_zero") is True,
        "search_completed": search_runtime.get("search_completed") is True,
        "semantic_search_used": bool(search_runtime.get("semantic_search_used")),
        "hybrid_search_used": bool(search_runtime.get("hybrid_search_used")),
        "qdrant_used": bool(search_runtime.get("qdrant_used")),
        "reranking_used": bool(search_runtime.get("reranking_used")),
        "llm_used": bool(search_runtime.get("llm_used")),
        "answer_generated": bool(search_runtime.get("answer_generated")),
        "tool_called": bool(search_runtime.get("tool_called")),
        "workflow_executed": bool(search_runtime.get("workflow_executed")),
        "external_action_called": bool(search_runtime.get("external_action_called")),
        "autonomous_execution": bool(search_runtime.get("autonomous_execution")),
        "postgresql_source_of_truth": search_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (search_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("assistant_search_execution", 0) >= 1,
    }
    expectations = {
        "assistant_search_execution_prepared": observed["assistant_search_execution_prepared"] is True,
        "retrieval_plan_created": observed["retrieval_plan_created"] is True,
        "execution_readiness_created": observed["execution_readiness_created"] is True,
        "enterprise_search_executed": observed["enterprise_search_executed"] is True,
        "postgresql_fts_used": observed["postgresql_fts_used"] is True,
        "lexical_search_used": observed["lexical_search_used"] is True,
        "result_count_gt_zero": observed["result_count_gt_zero"] is True,
        "search_completed": observed["search_completed"] is True,
        "semantic_search_used": observed["semantic_search_used"] is False,
        "hybrid_search_used": observed["hybrid_search_used"] is False,
        "qdrant_used": observed["qdrant_used"] is False,
        "reranking_used": observed["reranking_used"] is False,
        "llm_used": observed["llm_used"] is False,
        "answer_generated": observed["answer_generated"] is False,
        "tool_called": observed["tool_called"] is False,
        "workflow_executed": observed["workflow_executed"] is False,
        "external_action_called": observed["external_action_called"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "semantic_search_used": False,
        "hybrid_search_used": False,
        "qdrant_used": False,
        "reranking_used": False,
        "llm_used": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
    }
    for key, value in expectations.items():
        expected = expected_values.get(key, True)
        _expect(bool(value), failures, f"{key} must be {str(expected).lower()}")
    payload = {**observed, "passed": all(expectations.values()) and not failures, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
