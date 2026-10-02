from __future__ import annotations

import json

from main import app


def main() -> int:
    schema = app.openapi()
    path = schema.get("paths", {}).get("/api/control-plane/workers/summary", {}).get("get", {})
    model = schema.get("components", {}).get("schemas", {}).get("RuntimeWorkerSummaryRead", {})
    properties = model.get("properties", {})
    expected = {
        "total_workers",
        "active_desired",
        "ready_workers",
        "accepting_work",
        "stale_workers",
        "degraded_workers",
        "available_capacity_ratio",
    }
    checks = {
        "summary_endpoint": bool(path),
        "summary_schema": bool(model),
        "summary_fields": expected.issubset(properties),
        "ratio_number": properties.get("available_capacity_ratio", {}).get("type") == "number",
        "read_response": bool(path.get("responses", {}).get("200")),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
