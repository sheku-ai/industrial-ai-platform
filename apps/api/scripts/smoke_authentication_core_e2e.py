from __future__ import annotations

import argparse
import getpass
import json
import uuid
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)


def _request(opener, url: str, *, method: str = "GET", payload=None, headers=None):
    body = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read()
        try:
            content = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            content = None
        return exc.code, content


def run(base_url: str, email: str, password: str) -> dict:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    steps: list[dict] = []
    login_status, login = _request(
        opener,
        f"{base_url}/auth/login",
        method="POST",
        payload={"email": email, "password": password},
    )
    steps.append({"step": "login", "status": login_status})
    if login_status != 200:
        return {"passed": False, "steps": steps, "failure": "login_failed"}
    serialized_login = json.dumps(login).lower()
    if any(secret_key in serialized_login for secret_key in ("password_hash", "token_hash", "csrf_token")):
        return {"passed": False, "steps": steps, "failure": "sensitive_login_response"}

    me_status, me = _request(opener, f"{base_url}/auth/me")
    steps.append({"step": "auth_me", "status": me_status})
    memberships = list((me or {}).get("memberships") or [])
    if me_status != 200 or not memberships:
        return {"passed": False, "steps": steps, "failure": "membership_unavailable"}
    organization_id = str(memberships[0]["organization_id"])
    membership_organization_ids = {
        str(item["organization_id"])
        for item in memberships
        if item.get("status") == "active"
    }

    organizations_status, organizations = _request(
        opener,
        f"{base_url}/api/core/organizations?limit=500",
        headers={"X-Authorization-Scope": "platform"},
    )
    steps.append({"step": "authorized_organization_discovery", "status": organizations_status})
    discovered_organization_ids = {
        str(item["id"])
        for item in (organizations or [])
    }
    if (
        organizations_status != 200
        or discovered_organization_ids != membership_organization_ids
    ):
        return {
            "passed": False,
            "steps": steps,
            "failure": "organization_discovery_mismatch",
        }

    csrf_status, csrf = _request(opener, f"{base_url}/auth/csrf")
    steps.append({"step": "csrf", "status": csrf_status})
    csrf_token = str((csrf or {}).get("csrf_token") or "")
    csrf_header = str((csrf or {}).get("header_name") or "X-CSRF-Token")
    if csrf_status != 200 or not csrf_token:
        return {"passed": False, "steps": steps, "failure": "csrf_unavailable"}

    authorized_status, _ = _request(
        opener,
        f"{base_url}/api/documents/document-types",
        headers={
            "X-Authorization-Scope": "organization",
            "X-Organization-ID": organization_id,
        },
    )
    steps.append({"step": "authorized_organization", "status": authorized_status})

    unauthorized_status, _ = _request(
        opener,
        f"{base_url}/api/documents/document-types",
        headers={
            "X-Authorization-Scope": "organization",
            "X-Organization-ID": str(uuid.uuid4()),
        },
    )
    steps.append({"step": "organization_isolation", "status": unauthorized_status})

    logout_status, _ = _request(
        opener,
        f"{base_url}/auth/logout",
        method="POST",
        payload={},
        headers={csrf_header: csrf_token},
    )
    steps.append({"step": "logout", "status": logout_status})
    after_logout_status, _ = _request(opener, f"{base_url}/auth/me")
    steps.append({"step": "session_revoked", "status": after_logout_status})

    passed = (
        authorized_status == 200
        and unauthorized_status == 403
        and logout_status == 204
        and after_logout_status == 401
    )
    return {
        "passed": passed,
        "organization_id": organization_id,
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Authentication Core API smoke")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    try:
        result = run(args.base_url.rstrip("/"), email, password)
    except (URLError, TimeoutError, ValueError) as exc:
        result = {
            "passed": False,
            "failure": type(exc).__name__,
            "steps": [],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
