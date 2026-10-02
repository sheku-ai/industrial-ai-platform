"""Manual E2E smoke for Assistant Chat Runtime over the public API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
REQUESTED_BY = os.getenv("CHAT_SMOKE_REQUESTED_BY", "smoke-chat-runtime")
MESSAGE = os.getenv(
    "CHAT_SMOKE_MESSAGE",
    "inspection interval 45 days ACC-REF-001",
)
ASSISTANT_ID = os.getenv("CHAT_SMOKE_ASSISTANT_ID")
ORGANIZATION_ID = os.getenv("CHAT_SMOKE_ORGANIZATION_ID")
DOCUMENT_TYPE_ID = os.getenv("CHAT_SMOKE_DOCUMENT_TYPE_ID")
METADATA_TEMPLATE_ID = os.getenv("CHAT_SMOKE_METADATA_TEMPLATE_ID")
SMOKE_KEY = os.getenv("CHAT_SMOKE_KEY", f"chat-runtime-e2e-{int(time.time())}")
REFERENCE_CODE = "ACC-REF-001"
ACTOR_REFERENCE = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-administrator")
PRINCIPAL_TYPE = os.getenv("SMOKE_PRINCIPAL_TYPE", "reference_principal")
REQUEST_ORGANIZATION_ID: str | None = ORGANIZATION_ID
REFERENCE_TEXT = (
    "Assistant chat smoke reference. The governed inspection interval is 45 days. "
    f"The governing reference code is {REFERENCE_CODE}. This text validates Enterprise Search, "
    "citation evidence and conversation persistence."
)


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


def _url(path: str) -> str:
    return f"{API_BASE_URL}{path}"


def _print_result(payload: dict[str, Any], exit_code: int) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
    sys.stdout.write("\n")
    sys.exit(exit_code)


def _decode_response(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {"raw_response": text}


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Authorization-Scope": "organization" if REQUEST_ORGANIZATION_ID else "platform",
        "X-Actor-Reference": ACTOR_REFERENCE,
        "X-Principal-Type": PRINCIPAL_TYPE,
    }
    if REQUEST_ORGANIZATION_ID:
        headers["X-Organization-ID"] = REQUEST_ORGANIZATION_ID
    request = urllib.request.Request(
        _url(path),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return _decode_response(response.read())
    except urllib.error.HTTPError as exc:
        raise SmokeHttpError(method, path, exc.code, _decode_response(exc.read())) from exc
    except urllib.error.URLError as exc:
        raise SmokeHttpError(method, path, None, str(exc.reason)) from exc


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "results", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _extract_id(value: Any, *keys: str) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in (*keys, "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _find_by(items: Any, **expected: str) -> dict[str, Any] | None:
    for item in _items(items):
        if isinstance(item, dict) and all(str(item.get(key) or "") == value for key, value in expected.items()):
            return item
    return None


def _resolve_or_create_organization() -> tuple[str, list[Any]]:
    if ORGANIZATION_ID:
        return ORGANIZATION_ID, []
    slug = f"smoke-{SMOKE_KEY}"
    existing = _request("GET", "/core/organizations")
    reference = _find_by(existing, slug="reference-tenant")
    if reference:
        return str(_extract_id(reference, "organization_id")), []
    found = _find_by(existing, slug=slug)
    if found:
        return str(_extract_id(found, "organization_id")), []
    payload = {
        "slug": slug,
        "name": "Smoke Chat Runtime Organization",
        "description": "Generic organization used by chat runtime smoke.",
        "status": "active",
        "config": {"smoke_runtime": "chat_runtime_e2e"},
    }
    created = _request("POST", "/core/organizations", payload)
    organization_id = _extract_id(created, "organization_id")
    if not organization_id:
        raise SmokeHttpError("POST", "/core/organizations", None, {"payload": payload, "response": created})
    return organization_id, [{"organization_created": True, "organization_id": organization_id}]


def _resolve_or_create_probe_organization() -> tuple[str, list[Any]]:
    slug = f"smoke-{SMOKE_KEY}-isolation-probe"
    existing = _request("GET", "/core/organizations")
    for item in _items(existing):
        candidate = _extract_id(item, "organization_id")
        if candidate and candidate != REQUEST_ORGANIZATION_ID:
            return candidate, []
    found = _find_by(existing, slug=slug)
    if found:
        return str(_extract_id(found, "organization_id")), []
    payload = {
        "slug": slug,
        "name": "Smoke Chat Runtime Isolation Probe",
        "description": "Generic probe organization used by chat runtime smoke.",
        "status": "active",
        "config": {"smoke_runtime": "chat_runtime_e2e", "isolation_probe": True},
    }
    created = _request("POST", "/core/organizations", payload)
    organization_id = _extract_id(created, "organization_id")
    if not organization_id:
        raise SmokeHttpError("POST", "/core/organizations", None, {"payload": payload, "response": created})
    return organization_id, [{"probe_organization_created": True, "organization_id": organization_id}]


def _resolve_or_create_document_type(organization_id: str) -> tuple[str, list[Any]]:
    if DOCUMENT_TYPE_ID:
        return DOCUMENT_TYPE_ID, []
    code = f"{SMOKE_KEY.replace('-', '_')}_document_type"
    existing = _request("GET", "/documents/document-types")
    found = _find_by(existing, code=code, organization_id=organization_id)
    if found:
        return str(_extract_id(found, "document_type_id")), []
    payload = {
        "organization_id": organization_id,
        "code": code,
        "name": "Smoke Chat Runtime Document Type",
        "description": "Generic document type used by chat runtime smoke.",
        "version": "1.0",
        "status": "active",
        "config": {"smoke_runtime": "chat_runtime_e2e"},
    }
    created = _request("POST", "/documents/document-types", payload)
    document_type_id = _extract_id(created, "document_type_id")
    if not document_type_id:
        raise SmokeHttpError("POST", "/documents/document-types", None, {"payload": payload, "response": created})
    return document_type_id, [{"document_type_created": True, "document_type_id": document_type_id}]


def _resolve_or_create_metadata_template(
    organization_id: str,
    document_type_id: str,
) -> tuple[str, list[Any]]:
    if METADATA_TEMPLATE_ID:
        return METADATA_TEMPLATE_ID, []
    code = f"{SMOKE_KEY.replace('-', '_')}_metadata_template"
    existing = _request("GET", "/documents/metadata-templates")
    found = _find_by(existing, code=code, organization_id=organization_id)
    if found:
        return str(_extract_id(found, "metadata_template_id")), []
    payload = {
        "organization_id": organization_id,
        "document_type_id": document_type_id,
        "code": code,
        "name": "Smoke Chat Runtime Metadata Template",
        "schema_definition": {
            "type": "object",
            "properties": {
                "smoke_runtime": {"type": "string"},
                "reference_code": {"type": "string"},
            },
            "required": [],
        },
        "status": "active",
    }
    created = _request("POST", "/documents/metadata-templates", payload)
    metadata_template_id = _extract_id(created, "metadata_template_id")
    if not metadata_template_id:
        raise SmokeHttpError("POST", "/documents/metadata-templates", None, {"payload": payload, "response": created})
    return metadata_template_id, [{"metadata_template_created": True, "metadata_template_id": metadata_template_id}]


def _prepare_knowledge(
    organization_id: str,
    document_type_id: str,
    metadata_template_id: str,
) -> tuple[dict[str, Any], list[Any]]:
    payload = {
        "registration": {
            "organization_id": organization_id,
            "title": "Smoke Chat Runtime Reference",
            "source_type": "smoke",
            "document_type_id": document_type_id,
            "metadata_template_id": metadata_template_id,
            "external_reference": f"{SMOKE_KEY}:reference-document",
            "description": "Generic smoke reference for chat runtime.",
            "source_ref": {"provider": "smoke", "reference": f"{SMOKE_KEY}:reference-document"},
            "metadata": {"smoke_runtime": "chat_runtime_e2e", "reference_code": REFERENCE_CODE},
            "classification": {"scope": "internal"},
            "requested_by": REQUESTED_BY,
        },
        "version_label": "smoke-v1",
        "file_name": f"{SMOKE_KEY}-reference.txt",
        "content_type": "text/plain",
        "content_text": REFERENCE_TEXT,
        "storage_provider": {"provider": "filesystem"},
        "search_query": "inspection interval 45 days ACC-REF-001",
        "search_config": {"filters": {"organization_id": organization_id}},
        "top_k": 5,
        "requested_by": REQUESTED_BY,
        "idempotency_key": f"{SMOKE_KEY}:document-lifecycle:v1",
        "lifecycle_metadata": {"smoke_runtime": "chat_runtime_e2e"},
    }
    lifecycle = _request("POST", "/documents/lifecycle/orchestrate", payload)
    warnings = list(_mapping(lifecycle).get("warnings") or [])
    return _mapping(lifecycle), warnings


def _create_assistant(organization_id: str) -> str:
    if ASSISTANT_ID:
        return ASSISTANT_ID
    payload = _request(
        "POST",
        "/assistants",
        {
            "assistant_name": "Smoke Chat Assistant",
            "assistant_key": f"smoke-{SMOKE_KEY}-assistant",
            "assistant_version": "1.0",
            "assistant_type": "knowledge_assistant",
            "default_search_mode": "enterprise_search",
            "allowed_runtime_domains": ["enterprise_search"],
            "requested_by": REQUESTED_BY,
            "requested_query": MESSAGE,
            "runtime_context": {"organization_id": organization_id, "smoke_runtime": "chat_runtime_e2e"},
            "runtime_metadata": {"organization_id": organization_id, "smoke_runtime": "chat_runtime_e2e"},
        },
    )
    assistant_id = _extract_id(payload, "assistant_id")
    if not assistant_id and isinstance(payload, dict):
        assistant_id = _extract_id(payload.get("assistant"), "assistant_id")
    if not assistant_id:
        raise SmokeHttpError("POST", "/assistants", None, {"response": payload})
    return assistant_id


def _require(payload: dict[str, Any], key: str, warnings: list[str]) -> object | None:
    value = payload.get(key)
    if value in (None, "", [], {}):
        warnings.append(f"missing_{key}")
        return None
    return value


def run_smoke() -> dict[str, Any]:
    global REQUEST_ORGANIZATION_ID

    warnings: list[Any] = []
    setup_actions: list[Any] = []
    errors: list[Any] = []
    try:
        health = _mapping(_request("GET", "/assistants/chat/health"))
        if not health.get("chat_runtime_available"):
            errors.append({"code": "chat_runtime_not_available", "details": health})
            return {"passed": False, "warnings": warnings, "errors": errors}

        organization_id, org_warnings = _resolve_or_create_organization()
        REQUEST_ORGANIZATION_ID = organization_id
        setup_actions.extend(org_warnings)
        document_type_id, doc_type_warnings = _resolve_or_create_document_type(organization_id)
        setup_actions.extend(doc_type_warnings)
        metadata_template_id, template_warnings = _resolve_or_create_metadata_template(
            organization_id,
            document_type_id,
        )
        setup_actions.extend(template_warnings)
        probe_organization_id, probe_warnings = _resolve_or_create_probe_organization()
        setup_actions.extend(probe_warnings)
        lifecycle, lifecycle_warnings = _prepare_knowledge(organization_id, document_type_id, metadata_template_id)
        warnings.extend(lifecycle_warnings)
        assistant_id = _create_assistant(organization_id)

        chat_payload = {
            "assistant_id": assistant_id,
            "conversation_id": None,
            "message": MESSAGE,
            "requested_by": REQUESTED_BY,
            "runtime_context": {
                "organization_id": organization_id,
                "top_k": 5,
                "search_config": {"filters": {"organization_id": organization_id}},
                "smoke_runtime": "chat_runtime_e2e",
            },
            "runtime_metadata": {
                "organization_id": organization_id,
                "smoke_runtime": "chat_runtime_e2e",
            },
        }
        chat = _mapping(_request("POST", "/assistants/chat", chat_payload))
        conversation_id = _require(chat, "conversation_id", warnings)
        assistant_session_id = _require(chat, "assistant_session_id", warnings)
        assistant_run_id = _require(chat, "assistant_run_id", warnings)
        response_text = _require(chat, "response_text", warnings)
        assistant_response_id = chat.get("assistant_response_id")
        citation_verification_id = chat.get("citation_verification_id")
        search_execution_id = chat.get("search_execution_id")
        context_package_id = chat.get("context_package_id")
        prompt_package_id = chat.get("prompt_package_id")
        llm_execution_id = chat.get("llm_execution_id")
        assistant_response_read = (
            _mapping(
                _request(
                    "GET",
                    f"/assistants/responses/{assistant_response_id}?organization_id={organization_id}",
                )
            )
            if assistant_response_id
            else {}
        )
        repeated_response = (
            _mapping(
                _request(
                    "POST",
                    f"/assistants/citation-verifications/{citation_verification_id}/response",
                    {
                        "response_metadata": {
                            "organization_id": organization_id,
                            "smoke_runtime": "chat_runtime_e2e",
                            "idempotency_probe": True,
                        }
                    },
                )
            )
            if citation_verification_id
            else {}
        )
        cross_org_read_blocked = False
        if assistant_response_id:
            REQUEST_ORGANIZATION_ID = probe_organization_id
            try:
                _request(
                    "GET",
                    f"/assistants/responses/{assistant_response_id}?organization_id={probe_organization_id}",
                )
            except SmokeHttpError as exc:
                cross_org_read_blocked = exc.status_code == 403
            finally:
                REQUEST_ORGANIZATION_ID = organization_id

        conversation = _mapping(_request("GET", f"/assistants/chat/{conversation_id}")) if conversation_id else {}
        turns = conversation.get("conversation_turns")
        if turns is None:
            turns = conversation.get("turns")
        assistant_responses = conversation.get("assistant_responses")
        expected_false_flags = (
            "tool_called",
            "workflow_executed",
            "external_action_called",
            "autonomous_execution",
        )
        llm_used = bool(chat.get("llm_used"))
        embeddings_used = bool(chat.get("embeddings_used"))
        qdrant_used = bool(chat.get("qdrant_used"))
        checks = {
            "lifecycle_completed": lifecycle.get("lifecycle_completed") is True,
            "knowledge_indexed": lifecycle.get("knowledge_indexed") is True,
            "enterprise_search_visible": lifecycle.get("enterprise_search_visible") is True,
            "chat_completed": chat.get("chat_completed") is True,
            "conversation_persisted": bool(conversation_id and conversation.get("conversation")),
            "turns_persisted": isinstance(turns, list) and len(turns) >= 2,
            "assistant_response_persisted": bool(assistant_response_id)
            and isinstance(assistant_responses, list)
            and any(
                isinstance(item, dict) and item.get("assistant_response_id") == assistant_response_id
                for item in assistant_responses
            ),
            "assistant_response_read_scoped": assistant_response_read.get("assistant_response_read_allowed") is True
            and assistant_response_read.get("assistant_response_id") == assistant_response_id,
            "assistant_response_cross_org_blocked": cross_org_read_blocked,
            "assistant_response_idempotent": repeated_response.get("assistant_response_id") == assistant_response_id,
            "search_lineage_present": bool(search_execution_id and context_package_id),
            "prompt_lineage_present": bool(prompt_package_id and llm_execution_id),
            "citation_lineage_present": bool(citation_verification_id and assistant_response_id),
            "postgresql_source_of_truth": chat.get("postgresql_source_of_truth") is True,
            "llm_not_used": not llm_used,
            "embeddings_not_used": not embeddings_used,
            "qdrant_not_used": not qdrant_used,
            "side_effects_bounded": all(chat.get(flag) is False for flag in expected_false_flags),
        }
        for key, passed in checks.items():
            if not passed:
                errors.append({"code": f"{key}_failed"})
        warnings.extend(chat.get("warnings") or [])
        warnings.extend(conversation.get("warnings") or [])
        return {
            "passed": not errors,
            "api_base_url": API_BASE_URL,
            "organization_id": organization_id,
            "probe_organization_id": probe_organization_id,
            "document_type_id": document_type_id,
            "metadata_template_id": metadata_template_id,
            "assistant_id": assistant_id,
            "conversation_id": conversation_id,
            "assistant_session_id": assistant_session_id,
            "assistant_run_id": assistant_run_id,
            "assistant_response_id": assistant_response_id,
            "replayed_assistant_response_id": repeated_response.get("assistant_response_id"),
            "citation_verification_id": citation_verification_id,
            "llm_execution_id": llm_execution_id,
            "search_execution_id": search_execution_id,
            "context_package_id": context_package_id,
            "prompt_package_id": prompt_package_id,
            "turn_count": len(turns) if isinstance(turns, list) else 0,
            "response_text_preview": str(response_text or "")[:240],
            **checks,
            "llm_used": llm_used,
            "embeddings_used": embeddings_used,
            "qdrant_used": qdrant_used,
            "setup_actions": setup_actions,
            "warnings": warnings,
            "errors": errors,
        }
    except SmokeHttpError as exc:
        return {
            "passed": False,
            "api_base_url": API_BASE_URL,
            "setup_actions": setup_actions,
            "warnings": warnings,
            "errors": [*errors, {"code": "api_request_failed", "details": exc.as_dict()}],
        }


if __name__ == "__main__":
    result = run_smoke()
    _print_result(result, 0 if result.get("passed") else 1)
