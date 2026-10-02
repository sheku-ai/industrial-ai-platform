from __future__ import annotations

import ipaddress
import json
import time
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any
from urllib import error, parse, request

TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class _LoopbackSecureCookiePolicy(DefaultCookiePolicy):
    """Apply browser-equivalent Secure cookie handling only on loopback."""

    @staticmethod
    def _is_loopback_request(request_object: Any) -> bool:
        host = parse.urlsplit(request_object.get_full_url()).hostname
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host or "").is_loopback
        except ValueError:
            return False

    def return_ok_secure(self, cookie: Any, request_object: Any) -> bool:
        scheme = parse.urlsplit(request_object.get_full_url()).scheme
        if (
            cookie.secure
            and scheme not in self.secure_protocols
            and self._is_loopback_request(request_object)
        ):
            return True
        return super().return_ok_secure(cookie, request_object)


@dataclass
class HttpResult:
    ok: bool
    status_code: int
    method: str
    path: str
    data: Any = None
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class AcceptanceHttpClient:
    def __init__(self, base_url: str, correlation_id: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.correlation_id = correlation_id
        self.timeout = timeout
        self.organization_id: str | None = None
        self.authorization_scope: str | None = None
        self.principal_id: str | None = None
        self.csrf_token: str | None = None
        self.csrf_header_name = "X-CSRF-Token"
        self.cookie_jar = CookieJar(policy=_LoopbackSecureCookiePolicy())
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookie_jar))

    def authenticate(self, email: str | None, password: str | None) -> HttpResult:
        if not email or not password:
            return HttpResult(
                False,
                0,
                "POST",
                "/../auth/login",
                error="acceptance_authentication_credentials_not_configured",
            )
        login = self.request(
            "POST",
            "/../auth/login",
            payload={"email": email, "password": password, "remember_me": False},
            include_scope=False,
            include_csrf=False,
        )
        if not login.ok:
            return login
        user = login.data.get("user") if isinstance(login.data, dict) else None
        self.principal_id = str(user.get("id")) if isinstance(user, dict) and user.get("id") else None
        csrf = self.request(
            "GET",
            "/../auth/csrf",
            include_scope=False,
            include_csrf=False,
        )
        if not csrf.ok:
            return csrf
        if not isinstance(csrf.data, dict) or not csrf.data.get("csrf_token"):
            return HttpResult(False, csrf.status_code, "GET", "/../auth/csrf", error="csrf_token_missing")
        self.csrf_token = str(csrf.data["csrf_token"])
        self.csrf_header_name = str(csrf.data.get("header_name") or self.csrf_header_name)
        self.set_platform_scope()
        return login

    def logout_best_effort(self) -> None:
        if not self.csrf_token:
            return
        self.request("POST", "/../auth/logout", payload={}, include_scope=False)
        self.cookie_jar.clear()
        self.csrf_token = None
        self.principal_id = None
        self.authorization_scope = None
        self.organization_id = None

    def set_platform_scope(self) -> None:
        self.authorization_scope = "platform"
        self.organization_id = None

    def set_organization_scope(self, organization_id: str) -> None:
        self.authorization_scope = "organization"
        self.organization_id = organization_id

    def get(self, path: str, query: dict[str, Any] | None = None) -> HttpResult:
        return self.request("GET", path, query=query)

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> HttpResult:
        return self.request("POST", path, payload=payload or {}, idempotency_key=idempotency_key)

    def put(self, path: str, payload: dict[str, Any] | None = None) -> HttpResult:
        return self.request("PUT", path, payload=payload or {})

    def patch(self, path: str, payload: dict[str, Any] | None = None) -> HttpResult:
        return self.request("PATCH", path, payload=payload or {})

    def delete(self, path: str) -> HttpResult:
        return self.request("DELETE", path)

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        *,
        include_scope: bool = True,
        include_csrf: bool = True,
    ) -> HttpResult:
        url = self._url(path, query=query)
        body = None
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": self.correlation_id,
        }
        if include_scope and self.authorization_scope == "platform":
            headers["X-Authorization-Scope"] = "platform"
        elif include_scope and self.authorization_scope == "organization" and self.organization_id:
            headers.update(
                {
                    "X-Authorization-Scope": "organization",
                    "X-Organization-ID": self.organization_id,
                }
            )
        if include_csrf and method.upper() not in SAFE_METHODS and self.csrf_token:
            headers[self.csrf_header_name] = self.csrf_token
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        last_result: HttpResult | None = None
        for attempt in range(3):
            try:
                req = request.Request(url, data=body, headers=headers, method=method)
                with self.opener.open(req, timeout=self.timeout) as response:
                    raw = response.read()
                    data = _parse_json(raw)
                    return HttpResult(
                        True,
                        response.status,
                        method,
                        path,
                        data=data,
                        headers=dict(response.headers),
                    )
            except error.HTTPError as exc:
                data = _parse_json(exc.read())
                last_result = HttpResult(
                    False,
                    exc.code,
                    method,
                    path,
                    data=data,
                    error=_safe_error(data),
                    headers=dict(exc.headers or {}),
                )
                if exc.code not in TRANSIENT_STATUSES:
                    return last_result
            except TimeoutError:
                last_result = HttpResult(False, 0, method, path, error="timeout")
            except error.URLError as exc:
                last_result = HttpResult(False, 0, method, path, error=str(exc.reason))
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
        return last_result or HttpResult(False, 0, method, path, error="request_failed")

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        if path.startswith("/../"):
            root = self.base_url.removesuffix("/api")
            url = f"{root}/{path.removeprefix('/../')}"
            if query:
                compact = {key: value for key, value in query.items() if value is not None}
                if compact:
                    url = f"{url}?{parse.urlencode(compact)}"
            return url
        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{clean_path}"
        if query:
            compact = {key: value for key, value in query.items() if value is not None}
            if compact:
                url = f"{url}?{parse.urlencode(compact)}"
        return url


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": raw.decode("utf-8", errors="replace")}


def _safe_error(data: Any) -> str:
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data
        return str(detail)[:1000]
    return str(data)[:1000]
