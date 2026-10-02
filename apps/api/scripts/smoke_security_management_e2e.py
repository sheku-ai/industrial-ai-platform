"""Manual E2E smoke for Security Management over the public API."""

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
PRINCIPAL_ID = os.environ.get("SMOKE_PRINCIPAL_ID", f"smoke-principal-{time.time_ns()}")
PRINCIPAL_TYPE = os.environ.get("SMOKE_PRINCIPAL_TYPE", "user")


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


def _failure(error_code: str, details: Any) -> dict[str, Any]:
    return {
        "passed": False,
        "organization_id": ORGANIZATION_ID,
        "permission_id": None,
        "role_id": None,
        "assignment_id": None,
        "permission_created": False,
        "role_created": False,
        "role_permission_attached": False,
        "assignment_created": False,
        "effective_permission_present": False,
        "assignment_deactivated": False,
        "effective_permission_removed_after_deactivate": False,
        "assignment_reactivated": False,
        "effective_permission_present_after_reactivate": False,
        "readiness_returned": False,
        "postgresql_source_of_truth": True,
        "jwt_used": False,
        "llm_used": False,
        "embeddings_used": False,
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
                "slug": f"smoke-security-management-{suffix}",
                "name": f"Smoke Security Management {suffix}",
                "description": "Autocreated by Security Management smoke.",
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


def _resolve_permissions(organization_id: str, principal_id: str) -> dict[str, Any]:
    return http_post_json(
        "/security/management/principals/resolve-permissions",
        {
            "principal_type": PRINCIPAL_TYPE,
            "principal_id": principal_id,
            "organization_id": organization_id,
            "scope": "organization",
        },
    )


def main() -> int:
    organization_id, failure = resolve_first_or_create_organization()
    if failure is not None:
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1
    suffix = str(time.time_ns())
    resource = f"smoke.security.{suffix}"
    action = "read"
    expected_permission = f"{resource}:{action}"
    result: dict[str, Any] = {
        "passed": False,
        "organization_id": organization_id,
        "permission_id": None,
        "role_id": None,
        "assignment_id": None,
        "principal_id": PRINCIPAL_ID,
        "permission_created": False,
        "role_created": False,
        "role_permission_attached": False,
        "assignment_created": False,
        "effective_permission_present": False,
        "assignment_deactivated": False,
        "effective_permission_removed_after_deactivate": False,
        "assignment_reactivated": False,
        "effective_permission_present_after_reactivate": False,
        "readiness_returned": False,
        "postgresql_source_of_truth": True,
        "jwt_used": False,
        "llm_used": False,
        "embeddings_used": False,
        "qdrant_used": False,
        "warnings": [],
        "errors": [],
    }
    try:
        permission = http_post_json(
            "/security/management/permissions",
            {
                "resource": resource,
                "action": action,
                "description": "Security Management smoke permission.",
            },
        )
        permission_id = extract_id(permission, "permission_id")
        result["permission_id"] = permission_id
        result["permission_created"] = bool(permission_id)

        role = http_post_json(
            "/security/management/roles",
            {
                "organization_id": organization_id,
                "code": f"smoke-security-role-{suffix}",
                "name": f"Smoke Security Role {suffix}",
                "description": "Security Management smoke role.",
                "config": {"smoke": True, "requested_by": REQUESTED_BY},
                "status": "active",
            },
        )
        role_id = extract_id(role, "role_id")
        result["role_id"] = role_id
        result["role_created"] = bool(role_id)

        role_permission = http_post_json(f"/security/management/roles/{role_id}/permissions/{permission_id}", {})
        result["role_permission_attached"] = isinstance(role_permission, dict) and bool(role_permission.get("attached"))

        assignment = http_post_json(
            "/security/management/role-assignments",
            {
                "organization_id": organization_id,
                "role_id": role_id,
                "principal_type": PRINCIPAL_TYPE,
                "principal_id": PRINCIPAL_ID,
                "scope_type": "organization",
                "scope_id": organization_id,
                "status": "active",
            },
        )
        assignment_id = extract_id(assignment, "assignment_id")
        result["assignment_id"] = assignment_id
        result["assignment_created"] = bool(assignment_id)

        effective = _resolve_permissions(organization_id, PRINCIPAL_ID)
        result["effective_permission_present"] = expected_permission in (effective.get("permissions") or [])
        result["jwt_used"] = bool(effective.get("jwt_used"))
        result["llm_used"] = bool(effective.get("llm_used"))
        result["embeddings_used"] = bool(effective.get("embeddings_used"))
        result["qdrant_used"] = bool(effective.get("qdrant_used"))
        result["postgresql_source_of_truth"] = bool(effective.get("postgresql_source_of_truth"))

        deactivated = http_post_json(f"/security/management/role-assignments/{assignment_id}/deactivate", {})
        result["assignment_deactivated"] = isinstance(deactivated, dict) and deactivated.get("status") == "inactive"

        after_deactivate = _resolve_permissions(organization_id, PRINCIPAL_ID)
        result["effective_permission_removed_after_deactivate"] = expected_permission not in (
            after_deactivate.get("permissions") or []
        )

        reactivated = http_post_json(f"/security/management/role-assignments/{assignment_id}/activate", {})
        result["assignment_reactivated"] = isinstance(reactivated, dict) and reactivated.get("status") == "active"

        after_reactivate = _resolve_permissions(organization_id, PRINCIPAL_ID)
        result["effective_permission_present_after_reactivate"] = expected_permission in (
            after_reactivate.get("permissions") or []
        )

        readiness = http_get_json("/security/management/readiness")
        result["readiness_returned"] = isinstance(readiness, dict) and bool(readiness.get("postgresql_source_of_truth"))

        checks = (
            result["permission_created"],
            result["role_created"],
            result["role_permission_attached"],
            result["assignment_created"],
            result["effective_permission_present"],
            result["assignment_deactivated"],
            result["effective_permission_removed_after_deactivate"],
            result["assignment_reactivated"],
            result["effective_permission_present_after_reactivate"],
            result["readiness_returned"],
            result["postgresql_source_of_truth"] is True,
            result["jwt_used"] is False,
            result["llm_used"] is False,
            result["embeddings_used"] is False,
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
