#!/usr/bin/env python3
"""Manual smoke contract for Assistant LLM Execution Runtime."""

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
from app.services.assistant_llm_execution_runtime import build_assistant_llm_execution_runtime  # noqa: E402
from app.services.assistant_llm_gateway_runtime import build_assistant_llm_gateway_runtime  # noqa: E402
from app.services.assistant_prompt_assembly_runtime import build_assistant_prompt_assembly_runtime  # noqa: E402
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
    "Assistant LLM execution uses a deterministic local mock provider from an LLM gateway plan.\n"
    "The local mock produces raw model output metadata for validation without network calls.\n\n"
    "It does not verify citations, create a final response, call tools, execute workflows, or perform autonomous actions."
)
CONTENT_TYPE = "text/plain"
QUERY = "assistant llm execution deterministic local mock raw output"


def _upload_session() -> dict:
    artifact_id = str(uuid.uuid4())
    provider_descriptor = InMemoryStorageProvider().descriptor.as_dict()
    return {
        "upload_session_id": f"upload-session:{artifact_id}",
        "artifact_id": artifact_id,
        "document_record_id": str(uuid.uuid4()),
        "document_version_id": str(uuid.uuid4()),
        "requested_by": "assistant-llm-execution-smoke",
        "runtime_state": "ready",
        "runtime_trace": {},
        "storage_provider_descriptor": provider_descriptor,
        "execution_flags": {"storage_provider_name": "memory", "storage_provider_type": "memory"},
    }


def _request(upload_session: dict, operation: str, *, metadata: dict | None = None) -> dict:
    return build_storage_execution_request(
        upload_session,
        requested_operation=operation,
        requested_by="assistant-llm-execution-smoke",
        request_metadata=dict(metadata or {}),
        idempotency_key=f"assistant-llm-execution:{operation}:{upload_session['artifact_id']}",
    )


def _execution_request(result: dict) -> dict:
    value = result.get("execution_request")
    return value if isinstance(value, dict) else {}


def _object_handle(result: dict) -> dict | None:
    handle = _execution_request(result).get("object_handle")
    return handle if isinstance(handle, dict) else None


def _runtime_id(payload: dict | None, key: str, nested_key: str | None = None) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if value:
        return str(value)
    if nested_key:
        nested = payload.get(nested_key)
        if isinstance(nested, dict) and nested.get(key):
            return str(nested[key])
    return None


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
            "metadata": {"source": "assistant_llm_execution_smoke"},
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

    assistant_key = f"assistant-llm-execution-smoke-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        build_knowledge_index(db, publication)
        assistant_runtime = build_assistant_runtime(
            db,
            organization_id=None,
            ownership_scope="global",
            data_origin="validation",
            assistant_name="Assistant LLM Execution Smoke",
            assistant_key=assistant_key,
            assistant_version="1.0",
            assistant_type="platform_assistant",
            default_search_mode="enterprise_search",
            allowed_runtime_domains=["enterprise_search", "hybrid_search_runtime", "semantic_search_runtime", "workflow_runtime"],
            requested_by="assistant-llm-execution-e2e-smoke",
            conversation_reference=f"conversation:{assistant_key}",
            requested_query=QUERY,
            persist_snapshot=False,
        )
        retrieval_runtime = build_assistant_retrieval_runtime(
            db,
            assistant_id=_runtime_id(assistant_runtime, "assistant_id", "assistant_definition"),
            assistant_session_id=_runtime_id(assistant_runtime, "assistant_session_id", "assistant_session"),
            requested_query=QUERY,
            selected_search_mode="enterprise_search",
            persist_snapshot=False,
        )
        retrieval_plan_id = _runtime_id(retrieval_runtime, "retrieval_plan_id", "assistant_retrieval_plan")
        readiness_runtime = build_assistant_retrieval_execution_readiness_runtime(db, retrieval_plan_id=retrieval_plan_id, persist_snapshot=False)
        execution_plan_id = _runtime_id(readiness_runtime, "execution_plan_id", "assistant_retrieval_execution_plan")
        search_runtime = build_assistant_search_execution_runtime(
            db,
            execution_plan_id=execution_plan_id,
            top_k=10,
            search_config={"artifact_id": artifact_id, "content_type": CONTENT_TYPE},
            persist_snapshot=False,
        )
        search_execution_id = _runtime_id(search_runtime, "search_execution_id", "assistant_search_execution")
        context_runtime = build_assistant_context_builder_runtime(db, search_execution_id=search_execution_id, persist_snapshot=False)
        context_package_id = _runtime_id(context_runtime, "context_package_id", "assistant_context_package")
        prompt_runtime = build_assistant_prompt_assembly_runtime(db, context_package_id=context_package_id, persist_snapshot=False)
        prompt_package_id = _runtime_id(prompt_runtime, "prompt_package_id", "assistant_prompt_package")
        llm_gateway_runtime = build_assistant_llm_gateway_runtime(db, prompt_package_id=prompt_package_id, persist_snapshot=False)
        gateway_id = _runtime_id(llm_gateway_runtime, "gateway_id", "assistant_llm_invocation_plan")
        llm_execution_runtime = build_assistant_llm_execution_runtime(db, gateway_id=gateway_id)
        persistence_execution_id = (llm_execution_runtime.get("runtime_persistence") or {}).get("execution_id") if llm_execution_runtime else None
        readback = read_runtime_persistence(db, execution_id=persistence_execution_id) if persistence_execution_id else {}
    finally:
        db.close()

    llm_execution_runtime = llm_execution_runtime or {}
    observed = {
        "assistant_llm_execution_prepared": llm_execution_runtime.get("assistant_llm_execution_prepared") is True,
        "llm_gateway_created": llm_execution_runtime.get("llm_gateway_created") is True,
        "llm_execution_created": llm_execution_runtime.get("llm_execution_created") is True,
        "provider_type": llm_execution_runtime.get("provider_type"),
        "provider_called": llm_execution_runtime.get("provider_called") is True,
        "provider_call_mode": llm_execution_runtime.get("provider_call_mode"),
        "raw_output_created": llm_execution_runtime.get("raw_output_created") is True,
        "raw_output_persisted": llm_execution_runtime.get("raw_output_persisted") is True,
        "citation_verification_completed": bool(llm_execution_runtime.get("citation_verification_completed")),
        "final_response_created": bool(llm_execution_runtime.get("final_response_created")),
        "tool_called": bool(llm_execution_runtime.get("tool_called")),
        "workflow_executed": bool(llm_execution_runtime.get("workflow_executed")),
        "external_action_called": bool(llm_execution_runtime.get("external_action_called")),
        "autonomous_execution": bool(llm_execution_runtime.get("autonomous_execution")),
        "postgresql_source_of_truth": llm_execution_runtime.get("postgresql_source_of_truth") is True,
        "runtime_persistence": (llm_execution_runtime.get("runtime_persistence") or {}).get("persistence_completed") is True
        and readback.get("persistence_status") == "persisted"
        and (readback.get("domains") or {}).get("assistant_llm_execution", 0) >= 1,
    }
    expectations = {
        "assistant_llm_execution_prepared": observed["assistant_llm_execution_prepared"] is True,
        "llm_gateway_created": observed["llm_gateway_created"] is True,
        "llm_execution_created": observed["llm_execution_created"] is True,
        "provider_type": observed["provider_type"] == "local_mock",
        "provider_called": observed["provider_called"] is True,
        "provider_call_mode": observed["provider_call_mode"] == "deterministic_local_mock",
        "raw_output_created": observed["raw_output_created"] is True,
        "raw_output_persisted": observed["raw_output_persisted"] is True,
        "citation_verification_completed": observed["citation_verification_completed"] is False,
        "final_response_created": observed["final_response_created"] is False,
        "tool_called": observed["tool_called"] is False,
        "workflow_executed": observed["workflow_executed"] is False,
        "external_action_called": observed["external_action_called"] is False,
        "autonomous_execution": observed["autonomous_execution"] is False,
        "postgresql_source_of_truth": observed["postgresql_source_of_truth"] is True,
        "runtime_persistence": observed["runtime_persistence"] is True,
    }
    for key, value in expectations.items():
        _expect(bool(value), failures, f"{key} must match assistant llm execution contract")
    payload = {**observed, "passed": all(expectations.values()) and not failures, "failures": failures}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
