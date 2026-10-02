import json

from main import app


def main() -> int:
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    health = components.get("OperationalHealthResponse", {})
    issue = components.get("OperationalHealthIssue", {})
    checks = {
        "issues_field": "issues" in health.get("properties", {}),
        "issue_schema": bool(issue),
        "issue_code": "code" in issue.get("properties", {}),
        "issue_severity": "severity" in issue.get("properties", {}),
        "issue_resource": "resource_type" in issue.get("properties", {}),
        "issue_message": "message" in issue.get("properties", {}),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
