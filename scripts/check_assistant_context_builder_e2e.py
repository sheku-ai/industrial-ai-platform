#!/usr/bin/env python3
"""Manual smoke contract for Assistant Context Builder Runtime."""

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
from app.services.assistant_context_builder_runtime import build_assistant_context_builder_runtime  # noqa: E402
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
    "Assistant context builder packages Enterprise Search evidence into ordered context.\n"
    "The package includes ordered chunks, citations, token estimates and context statistics.\n\n"
    "No prompts, LLMs, answers, tools or workflows are executed."
)
CONTENT_TYPE = "text/plain"
QUERY = "assistant context builder ordered context citations"


def _upload_session() -> dict:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "assistant-context-builder-smoke",
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
        requested_by="assistant-context-builder-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"assistant-context-builder:{operation}:{upload_session['artifact_id']}",
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
            "metadata": {"source": "assistant_context_builder_smoke"},
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

    assistant_key = f"assistant-context-builder-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        build_knowledge_index(db, publication)
        assistant_runtime = build_assistant_runtime(
            db,
            organization_id=None,
            ownership_scope="global",
            data_origin="validation",
            assistant_name="Assistant Context Builder Smoke",
            assistant_key=assistant_key,
            assistant_version="1.0",
            assistant_type="platform_assistant",
            description="Assistant context builder smoke.",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search", "hybrid_search_runtime", "semantic_search_runtime", "workflow_runtime"],
            requested_by="assistant-context-builder-e2e-smoke",
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
            persist_snapshot=False,
        )
        context_runtime = build_assistant_context_builder_runtime(
            db,
            search_execution_id=search_runtime.get("search_execution_id"),
        )
        persistence_execution_id = (context_runtime.get("runtime_persistence") or {}).get("execution_id") if context_runtime else None
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    context_runtime = context_runtime or {}
    observed = {
        "assistant_context_builder_prepared": context_runtime.get("assistant_context_builder_prepared") is True,
        "search_execution_completed": context_runtime.get("search_execution_completed") is True,
        "context_package_created": context_runtime.get("context_package_created") is True,
        "ordered_context_created": context_runtime.get("ordered_context_created") is True,
        "ordered_citations_created": context_runtime.get("ordered_citations_created") is True,
        "chunk_count_gt_zero": context_runtime.get("chunk_count_gt_zero") is True,
        "citation_count_gt_zero": context_runtime.get("citation_count_gt_zero") is True,
        "token_estimation_completed": context_runtime.get("token_estimation_completed") is True,
        "truncation_required": bool(context_runtime.get("truncation_required")),
        "truncation_applied": bool(context_runtime.get("truncation_applied")),
        "llm_used": bool(context_runtime.get("llm_used")),
        "answer_generated": bool(context_runtime.get("answer_generated")),
        "workflow_executed": bool(context_runtime.get("workflow_executed")),
        "tool_called": bool(context_runtime.get("tool_called")),
        "external_action_called": bool(context_runtime.get("external_action_called")),
        "autonomous_execution": bool(context_runtime.get("autonomous_execution")),
        "postgresql_source_of_truth": context_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (context_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("assistant_context_builder", 0) >= 1,
    }
    expectations = {
        "assistant_context_builder_prepared": observed["assistant_context_builder_prepared"] is True,
        "search_execution_completed": observed["search_execution_completed"] is True,
        "context_package_created": observed["context_package_created"] is True,
        "ordered_context_created": observed["ordered_context_created"] is True,
        "ordered_citations_created": observed["ordered_citations_created"] is True,
        "chunk_count_gt_zero": observed["chunk_count_gt_zero"] is True,
        "citation_count_gt_zero": observed["citation_count_gt_zero"] is True,
        "token_estimation_completed": observed["token_estimation_completed"] is True,
        "truncation_required": observed["truncation_required"] is False,
        "truncation_applied": observed["truncation_applied"] is False,
        "llm_used": observed["llm_used"] is False,
        "answer_generated": observed["answer_generated"] is False,
        "workflow_executed": observed["workflow_executed"] is False,
        "tool_called": observed["tool_called"] is False,
        "external_action_called": observed["external_action_called"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    expected_values = {
        "truncation_required": False,
        "truncation_applied": False,
        "llm_used": False,
        "answer_generated": False,
        "workflow_executed": False,
        "tool_called": False,
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
