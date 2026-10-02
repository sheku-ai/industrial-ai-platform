from __future__ import annotations

import json

from main import app


def main() -> int:
    schema = app.openapi()
    paths = schema.get("paths", {})
    schemas = schema.get("components", {}).get("schemas", {})
    events = paths.get("/api/control-plane/workers/{worker_key}/events", {}).get("get", {})
    history = paths.get("/api/control-plane/workers/{worker_key}/history", {}).get("get", {})
    checks = {
        "events_endpoint": bool(events),
        "history_endpoint": bool(history),
        "events_schema": "RuntimeWorkerEventRead" in schemas,
        "history_schema": "RuntimeWorkerHistoryRead" in schemas,
        "events_limit": any(item.get("name") == "limit" for item in events.get("parameters", [])),
        "history_limit": any(item.get("name") == "limit" for item in history.get("parameters", [])),
        "events_response": bool(events.get("responses", {}).get("200")),
        "history_response": bool(history.get("responses", {}).get("200")),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
