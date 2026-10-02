"""Manual E2E smoke for Feedback and Audit UX over the public API."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib import error, request

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ORGANIZATION_ID = os.environ.get("SMOKE_ORGANIZATION_ID")
REQUESTED_BY = os.environ.get("SMOKE_REQUESTED_BY", "smoke")


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
    req = request.Request(
        f"{API_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
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


def _failure(error_code: str, details: Any) -> dict[str, Any]:
    return {
        "passed": False,
        "organization_id": ORGANIZATION_ID,
        "feedback_id": None,
        "feedback_persisted": False,
        "feedback_listed": False,
        "audit_explorer_ready": False,
        "runtime_explorer_ready": False,
        "conversation_history_ready": False,
        "assistant_history_ready": False,
        "search_history_ready": False,
        "document_lifecycle_history_ready": False,
        "readiness_returned": False,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
        "warnings": [],
        "errors": [{"error": error_code, "details": details}],
    }


def resolve_first_or_create_organization() -> tuple[str | None, dict[str, Any] | None]:
    if ORGANIZATION_ID:
        return ORGANIZATION_ID, None
    try:
        existing = http_get_json("/core/organizations")
        resolved = _first_id(existing, "organization_id")
        if resolved:
            return resolved, None
        suffix = str(time.time_ns())
        created = http_post_json(
            "/core/organizations",
            {
                "slug": f"smoke-feedback-audit-{suffix}",
                "name": f"Smoke Feedback Audit {suffix}",
                "description": "Autocreated by Feedback and Audit UX smoke.",
                "status": "active",
                "config": {"created_by": REQUESTED_BY},
            },
        )
        created_id = extract_id(created, "organization_id")
        if created_id:
            return created_id, None
        return None, _failure("unable_to_resolve_organization", created)
    except SmokeHttpError as exc:
        return None, _failure("unable_to_resolve_organization", exc.as_dict())


def _explorer_ready(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("items"), list)
        and value.get("postgresql_source_of_truth") is True
    )


def main() -> int:
    organization_id, failure = resolve_first_or_create_organization()
    if failure is not None:
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1
    suffix = str(time.time_ns())
    result: dict[str, Any] = {
        "passed": False,
        "organization_id": organization_id,
        "feedback_id": None,
        "feedback_persisted": False,
        "feedback_listed": False,
        "audit_explorer_ready": False,
        "runtime_explorer_ready": False,
        "conversation_history_ready": False,
        "assistant_history_ready": False,
        "search_history_ready": False,
        "document_lifecycle_history_ready": False,
        "readiness_returned": False,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "qdrant_used": False,
        "warnings": [],
        "errors": [],
    }
    try:
        feedback = http_post_json(
            "/feedback-audit/feedback",
            {
                "organization_id": organization_id,
                "target_type": "smoke",
                "target_id": f"feedback-audit-smoke-{suffix}",
                "rating": "positive",
                "comment": "Feedback and Audit UX smoke feedback.",
                "actor_type": "user",
                "actor_id": REQUESTED_BY,
                "metadata": {"smoke": True, "suffix": suffix},
            },
        )
        feedback_id = extract_id(feedback, "feedback_id")
        result["feedback_id"] = feedback_id
        result["feedback_persisted"] = isinstance(feedback, dict) and feedback.get("feedback_persisted") is True

        feedback_list = http_get_json(f"/feedback-audit/feedback?organization_id={organization_id}&target_type=smoke")
        result["feedback_listed"] = isinstance(feedback_list, list) and any(
            extract_id(item, "feedback_id") == feedback_id for item in feedback_list if isinstance(item, dict)
        )

        audit_events = http_get_json(f"/feedback-audit/audit/events?organization_id={organization_id}")
        result["audit_explorer_ready"] = _explorer_ready(audit_events)

        audit_history = http_get_json(f"/feedback-audit/audit/history?organization_id={organization_id}")
        result["audit_history_ready"] = _explorer_ready(audit_history)

        runtime_records = http_get_json("/feedback-audit/runtime/records")
        result["runtime_explorer_ready"] = _explorer_ready(runtime_records)

        runtime_executions = http_get_json(f"/feedback-audit/runtime/executions?organization_id={organization_id}")
        result["runtime_executions_ready"] = _explorer_ready(runtime_executions)

        conversations = http_get_json("/feedback-audit/conversations")
        result["conversation_history_ready"] = _explorer_ready(conversations)

        assistant_history = http_get_json("/feedback-audit/assistants/history")
        result["assistant_history_ready"] = _explorer_ready(assistant_history)

        search_history = http_get_json("/feedback-audit/search/history")
        result["search_history_ready"] = _explorer_ready(search_history)

        document_lifecycle = http_get_json(
            f"/feedback-audit/documents/lifecycle-history?organization_id={organization_id}"
        )
        result["document_lifecycle_history_ready"] = _explorer_ready(document_lifecycle)

        readiness = http_get_json("/feedback-audit/readiness")
        result["readiness_returned"] = isinstance(readiness, dict)
        result["postgresql_source_of_truth"] = (
            bool(readiness.get("postgresql_source_of_truth")) if isinstance(readiness, dict) else None
        )
        result["llm_used"] = bool(readiness.get("llm_used")) if isinstance(readiness, dict) else None
        result["qdrant_used"] = bool(readiness.get("qdrant_used")) if isinstance(readiness, dict) else None

        checks = (
            result["feedback_persisted"],
            result["feedback_listed"],
            result["audit_explorer_ready"],
            result["runtime_explorer_ready"],
            result["conversation_history_ready"],
            result["assistant_history_ready"],
            result["search_history_ready"],
            result["document_lifecycle_history_ready"],
            result["readiness_returned"],
            result["postgresql_source_of_truth"] is True,
            result["llm_used"] is False,
            result["qdrant_used"] is False,
        )
        result["passed"] = all(checks)
    except SmokeHttpError as exc:
        result["errors"].append(exc.as_dict())
        result["passed"] = False
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
