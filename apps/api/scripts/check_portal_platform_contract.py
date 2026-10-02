from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("PLATFORM_PORTAL_BASE_URL", "http://portal:3000").rstrip("/")


def _get(path: str) -> tuple[int, str, str]:
    request = Request(f"{BASE_URL}{path}", headers={"Accept": "text/html"})
    try:
        with urlopen(request, timeout=10) as response:
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read(200_000).decode("utf-8", errors="replace"),
            )
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {error.code}: {body[:300]}") from error
    except URLError as error:
        raise RuntimeError(f"{path} unavailable: {error.reason}") from error


def main() -> int:
    status, content_type, body = _get("/operations")
    normalized = body.lower()
    checks = {
        "operations_endpoint_ok": status == 200,
        "operations_returns_html": "text/html" in content_type.lower(),
        "operations_body_nonempty": len(body.strip()) > 0,
        "operations_has_document_markup": "<html" in normalized or "<!doctype html" in normalized,
        "portal_base_url_traceable": BASE_URL.startswith(("http://", "https://")),
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "portal_base_url": BASE_URL,
                "response_bytes": len(body.encode("utf-8")),
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
