from __future__ import annotations

import json

from main import app


def main() -> int:
    schema = app.openapi()
    paths = schema.get("paths", {})
    list_path = paths.get("/api/control-plane/workers", {})
    item_path = paths.get("/api/control-plane/workers/{worker_key}", {})
    command_path = paths.get(
        "/api/control-plane/workers/{worker_key}/desired-state",
        {},
    )

    checks = {
        "list_endpoint": "get" in list_path,
        "get_endpoint": "get" in item_path,
        "desired_state_endpoint": "put" in command_path,
        "list_response_typed": bool(
            list_path.get("get", {})
            .get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        ),
        "get_response_typed": bool(
            item_path.get("get", {})
            .get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        ),
        "command_request_typed": bool(
            command_path.get("put", {})
            .get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        ),
        "command_response_typed": bool(
            command_path.get("put", {})
            .get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        ),
        "worker_schema_present": "RuntimeWorkerRead" in schema.get("components", {}).get("schemas", {}),
        "desired_state_schema_present": "RuntimeWorkerDesiredStateUpdate"
        in schema.get("components", {}).get("schemas", {}),
    }

    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
