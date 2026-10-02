from __future__ import annotations

import json

from main import app


def main() -> int:
    schema = app.openapi()
    worker_schema = schema.get("components", {}).get("schemas", {}).get("RuntimeWorkerRead", {})
    properties = worker_schema.get("properties", {})
    required = set(worker_schema.get("required", []))
    expected = {
        "heartbeat_stale",
        "heartbeat_stale_after_seconds",
        "accepting_work",
        "ready",
    }
    checks = {
        "worker_schema_present": bool(worker_schema),
        "effective_fields_present": expected.issubset(properties),
        "effective_fields_required": expected.issubset(required),
        "heartbeat_stale_boolean": properties.get("heartbeat_stale", {}).get("type") == "boolean",
        "accepting_work_boolean": properties.get("accepting_work", {}).get("type") == "boolean",
        "ready_boolean": properties.get("ready", {}).get("type") == "boolean",
        "threshold_integer": properties.get("heartbeat_stale_after_seconds", {}).get("type") == "integer",
        "list_endpoint_present": "/api/control-plane/workers" in schema.get("paths", {}),
        "item_endpoint_present": "/api/control-plane/workers/{worker_key}" in schema.get("paths", {}),
        "command_endpoint_present": "/api/control-plane/workers/{worker_key}/desired-state" in schema.get("paths", {}),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
