import json

from main import app


def main() -> int:
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    health = components.get("OperationalHealthResponse", {})
    path = schema.get("paths", {}).get("/api/control-plane/health", {}).get("get", {})
    checks = {
        "health_endpoint": bool(path),
        "worker_control_plane_field": "worker_control_plane" in health.get("properties", {}),
        "worker_summary_schema": "RuntimeWorkerSummaryRead" in components,
        "response_200": bool(path.get("responses", {}).get("200")),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
