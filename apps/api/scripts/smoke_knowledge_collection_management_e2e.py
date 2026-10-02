"""Manual E2E smoke for Knowledge Collection Management over the public API."""

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


def http_patch_json(path: str, payload: dict[str, Any]) -> Any:
    return _http_json("PATCH", path, payload)


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


def _failure(error_code: str, details: Any, *, warnings: list[Any] | None = None) -> dict[str, Any]:
    return {
        "passed": False,
        "organization_id": ORGANIZATION_ID,
        "collection_id": None,
        "knowledge_source_id": None,
        "collection_created": False,
        "collection_listed": False,
        "collection_read": False,
        "collection_updated": False,
        "collection_deactivated": False,
        "collection_activated": False,
        "readiness_returned": False,
        "contents_returned": False,
        "knowledge_source_prepared": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "semantic_search_required": False,
        "postgresql_source_of_truth": True,
        "warnings": warnings or [],
        "errors": [{"error": error_code, "details": details}],
        "error": error_code,
        "details": details,
    }


def resolve_first_or_create_organization() -> tuple[str | None, dict[str, Any] | None]:
    if ORGANIZATION_ID:
        return ORGANIZATION_ID, None
    try:
        existing = http_get_json("/core/organizations")
        resolved = _first_id(existing, "organization_id")
        if resolved:
            return resolved, None
        suffix = str(int(time.time()))
        created = http_post_json(
            "/core/organizations",
            {
                "slug": f"smoke-knowledge-collection-{suffix}",
                "name": f"Smoke Knowledge Collection {suffix}",
                "description": "Autocreated by Knowledge Collection Management smoke.",
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


def main() -> int:
    warnings: list[Any] = []
    organization_id, failure = resolve_first_or_create_organization()
    if failure is not None:
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1
    suffix = str(int(time.time()))
    result: dict[str, Any] = {
        "passed": False,
        "organization_id": organization_id,
        "collection_id": None,
        "knowledge_source_id": None,
        "collection_created": False,
        "collection_listed": False,
        "collection_read": False,
        "collection_updated": False,
        "collection_deactivated": False,
        "collection_activated": False,
        "readiness_returned": False,
        "contents_returned": False,
        "knowledge_source_prepared": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "semantic_search_required": False,
        "postgresql_source_of_truth": True,
        "warnings": warnings,
        "errors": [],
    }
    try:
        created = http_post_json(
            "/knowledge/collections",
            {
                "organization_id": organization_id,
                "code": f"smoke-knowledge-collection-{suffix}",
                "name": f"Smoke Knowledge Collection {suffix}",
                "description": "Knowledge Collection Management smoke collection.",
                "config": {"smoke": True, "requested_by": REQUESTED_BY},
                "status": "active",
            },
        )
        collection_id = extract_id(created, "collection_id")
        result["collection_id"] = collection_id
        result["collection_created"] = bool(collection_id)

        listed = http_get_json(f"/knowledge/collections?organization_id={organization_id}")
        result["collection_listed"] = _first_id(listed, "collection_id") is not None and any(
            extract_id(item, "collection_id") == collection_id for item in listed if isinstance(item, dict)
        )

        read = http_get_json(f"/knowledge/collections/{collection_id}")
        result["collection_read"] = (
            extract_id(read, "collection_id") == collection_id or extract_id(read) == collection_id
        )

        updated = http_patch_json(
            f"/knowledge/collections/{collection_id}",
            {
                "description": "Updated by Knowledge Collection Management smoke.",
                "config": {"smoke": True, "updated": True, "requested_by": REQUESTED_BY},
            },
        )
        result["collection_updated"] = (
            bool(updated.get("config", {}).get("updated")) if isinstance(updated, dict) else False
        )

        deactivated = http_post_json(f"/knowledge/collections/{collection_id}/deactivate", {})
        result["collection_deactivated"] = isinstance(deactivated, dict) and deactivated.get("status") == "inactive"

        activated = http_post_json(f"/knowledge/collections/{collection_id}/activate", {})
        result["collection_activated"] = isinstance(activated, dict) and activated.get("status") == "active"

        readiness = http_get_json(f"/knowledge/collections/{collection_id}/readiness")
        result["readiness_returned"] = isinstance(readiness, dict) and readiness.get("collection_id") == collection_id
        result["llm_used"] = bool(readiness.get("llm_used")) if isinstance(readiness, dict) else None
        result["embeddings_used"] = bool(readiness.get("embeddings_used")) if isinstance(readiness, dict) else None
        result["qdrant_used"] = bool(readiness.get("qdrant_used")) if isinstance(readiness, dict) else None
        result["semantic_search_required"] = (
            bool(readiness.get("semantic_search_required")) if isinstance(readiness, dict) else None
        )
        result["postgresql_source_of_truth"] = (
            bool(readiness.get("postgresql_source_of_truth")) if isinstance(readiness, dict) else None
        )

        contents = http_get_json(f"/knowledge/collections/{collection_id}/contents")
        result["contents_returned"] = isinstance(contents, dict) and isinstance(contents.get("documents"), list)

        source = http_post_json(
            f"/knowledge/collections/{collection_id}/knowledge-source",
            {"source_type": "collection", "config": {"smoke": True, "requested_by": REQUESTED_BY}, "status": "active"},
        )
        result["knowledge_source_id"] = extract_id(source, "knowledge_source_id")
        result["knowledge_source_prepared"] = isinstance(source, dict) and bool(source.get("source_prepared"))

        checks = (
            result["collection_created"],
            result["collection_listed"],
            result["collection_read"],
            result["collection_updated"],
            result["collection_deactivated"],
            result["collection_activated"],
            result["readiness_returned"],
            result["contents_returned"],
            result["knowledge_source_prepared"],
            result["llm_used"] is False,
            result["embeddings_used"] is False,
            result["qdrant_used"] is False,
            result["semantic_search_required"] is False,
            result["postgresql_source_of_truth"] is True,
        )
        result["passed"] = all(checks)
    except SmokeHttpError as exc:
        result["errors"].append(exc.as_dict())
        result["passed"] = False
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
