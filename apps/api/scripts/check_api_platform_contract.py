from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("PLATFORM_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _get_json(path: str) -> tuple[int, dict]:
    request = Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {error.code}: {body[:300]}") from error
    except URLError as error:
        raise RuntimeError(f"{path} unavailable: {error.reason}") from error


def main() -> int:
    live_status, live = _get_json("/health/live")
    ready_status, ready = _get_json("/health/ready")
    openapi_status, openapi = _get_json("/openapi.json")

    paths = openapi.get("paths") if isinstance(openapi, dict) else None
    info = openapi.get("info") if isinstance(openapi, dict) else None
    components = openapi.get("components") if isinstance(openapi, dict) else None

    checks = {
        "live_endpoint_ok": live_status == 200 and isinstance(live, dict),
        "ready_endpoint_ok": ready_status == 200 and isinstance(ready, dict),
        "openapi_endpoint_ok": openapi_status == 200,
        "openapi_schema_version_present": isinstance(openapi.get("openapi"), str),
        "openapi_info_present": isinstance(info, dict) and bool(info.get("title")),
        "openapi_paths_nonempty": isinstance(paths, dict) and len(paths) > 0,
        "health_paths_documented": isinstance(paths, dict) and "/health/live" in paths and "/health/ready" in paths,
        "components_are_structured": components is None or isinstance(components, dict),
        "api_base_url_traceable": BASE_URL.startswith(("http://", "https://")),
    }
    passed = all(checks.values())
    result = {
        "passed": passed,
        "api_base_url": BASE_URL,
        "documented_path_count": len(paths) if isinstance(paths, dict) else 0,
        **checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
