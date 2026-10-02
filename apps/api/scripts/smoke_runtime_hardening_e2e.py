#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from readiness_contract_smoke import public_readiness_contract_valid

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
ACTOR = os.getenv("SMOKE_ACTOR_REFERENCE", "reference-platform-operator")
PRINCIPAL_TYPE = os.getenv("SMOKE_PRINCIPAL_TYPE", "reference_principal")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30"))

RUNTIME_ENDPOINTS = {
    "local_product_acceptance": "/product-acceptance/executions?limit=1",
    "production_acceptance": "/platform/production-acceptance/workspace?scope=platform",
    "production_readiness": "/platform/production-readiness/runtime",
    "security": "/platform/security/readiness?scope=platform",
    "recovery": "/platform/recovery/readiness?scope=platform",
    "release_governance": "/platform/releases/latest/readiness",
    "capacity": "/platform/capacity/readiness?scope=platform",
    "observability": "/platform/observability/readiness",
    "portal": "/platform/portal-acceptance/readiness",
}

EVIDENCE_CONTRACT_DOMAINS = {
    "security": "security",
    "recovery": "recovery",
    "capacity": "capacity",
    "observability": "observability",
    "portal": "portal",
}


def _call(path: str, headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers={"Accept": "application/json", **headers},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            detail: Any = json.loads(body)
        except json.JSONDecodeError:
            detail = body
        return exc.code, detail
    except urllib.error.URLError as exc:
        return 0, {"detail": "connection_failed", "reason": str(exc.reason)}


def _headers(
    *,
    scope: str = "platform",
    actor: str | None = ACTOR,
    organization_id: str | None = None,
    principal_type: str = PRINCIPAL_TYPE,
) -> dict[str, str]:
    headers = {
        "X-Authorization-Scope": scope,
        "X-Principal-Type": principal_type,
    }
    if actor is not None:
        headers["X-Actor-Reference"] = actor
    if organization_id is not None:
        headers["X-Organization-ID"] = organization_id
    return headers


def _organization_path(path: str, organization_id: str) -> str:
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key not in {"scope", "organization_id"}]
    query.extend((("scope", "organization"), ("organization_id", organization_id)))
    return urllib.parse.urlunsplit(("", "", parsed.path, urllib.parse.urlencode(query), ""))


def main() -> int:
    errors: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    missing_organization = str(uuid.uuid4())

    for runtime, path in RUNTIME_ENDPOINTS.items():
        success_status, success = _call(path, _headers())
        permission_status, _ = _call(
            path,
            _headers(
                actor="runtime-hardening-no-permissions",
                principal_type="runtime_hardening_unauthorized",
            ),
        )
        authentication_status, _ = _call(path, _headers(actor=None))
        invalid_scope_status, _ = _call(path, _headers(scope="invalid"))
        missing_org_status, _ = _call(
            _organization_path(path, missing_organization),
            _headers(scope="organization", organization_id=missing_organization),
        )

        checks = {
            "successful_case": success_status == 200,
            "permission_denied": permission_status == 403,
            "authentication_required": authentication_status == 401,
            "invalid_scope": invalid_scope_status == 400,
            "organization_not_found": missing_org_status == 404,
        }
        expected_domain = EVIDENCE_CONTRACT_DOMAINS.get(runtime)
        if expected_domain is not None and success_status == 200:
            checks["public_evidence_contract"] = public_readiness_contract_valid(
                success.get("evidence_contract") if isinstance(success, dict) else None,
                domain=expected_domain,
            )
        elif runtime == "production_readiness" and success_status == 200:
            checks["public_evidence_contract"] = all(
                public_readiness_contract_valid(item)
                for item in success.get("evidence_contracts", [])
            )
        elif runtime == "release_governance" and success_status == 200:
            readiness = success.get("readiness") if isinstance(success, dict) else None
            checks["public_evidence_contract"] = (
                success.get("found") is False
                or public_readiness_contract_valid(
                    readiness.get("evidence_contract") if isinstance(readiness, dict) else None,
                    domain="release_governance",
                )
            )

        failed_checks = [name for name, passed in checks.items() if not passed]
        if failed_checks:
            errors.append({"runtime": runtime, "failed_checks": failed_checks})
        results[runtime] = checks

    output = {
        "passed": not errors,
        "api_base_url": API_BASE_URL,
        "runtime_results": results,
        "errors": errors,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
