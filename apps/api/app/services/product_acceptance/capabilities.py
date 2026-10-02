from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.product_acceptance.contracts import REQUIRED_CAPABILITIES
from app.services.product_acceptance.gateway import AcceptanceHttpClient


def discover_capabilities(client: AcceptanceHttpClient) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    result = client.request("GET", "/product-acceptance/contract")
    if not result.ok:
        result = client.request("GET", "/../openapi.json")
    if not result.ok:
        result = client.request("GET", "/openapi.json")
    openapi = result.data if result.ok else {}
    paths = _extract_paths(openapi)
    matrix: list[dict[str, Any]] = []
    for requirement in REQUIRED_CAPABILITIES:
        endpoint = requirement["endpoint"]
        method = requirement["method"].lower()
        resolved_path, operation = resolve_openapi_operation(openapi, endpoint, method, client.base_url)
        path_exists = resolved_path is not None
        method_exists = operation is not None
        public_api_available = path_exists and method_exists
        if endpoint == "/openapi.json" and result.ok:
            path_exists = True
            method_exists = True
            public_api_available = True
            resolved_path = "/openapi.json"
        operation = operation or {}
        request_schema_available = _schema_available(operation, method, "requestBody", endpoint)
        response_schema_available = _response_schema_available(operation, endpoint)
        organization_scope_supported, organization_scope_field = _organization_scope_contract(openapi, operation)
        cleanup_supported = _cleanup_available(paths, resolved_path or endpoint)
        status = _capability_status(
            public_api_available=public_api_available,
            request_schema_available=request_schema_available,
            response_schema_available=response_schema_available,
            organization_scope_supported=organization_scope_supported,
            requirement=requirement,
        )
        error_code = _error_code_for_status(status, public_api_available, organization_scope_supported, requirement)
        matrix.append(
            {
                "capability": requirement["capability"],
                "capability_code": requirement["capability"],
                "required": requirement["required"],
                "phase_code": requirement.get("phase_code"),
                "public_path": endpoint,
                "requested_path": endpoint,
                "resolved_path": resolved_path,
                "http_method": requirement["method"],
                "path_exists": path_exists,
                "method_exists": method_exists,
                "public_api_available": public_api_available,
                "read_api_available": bool(resolved_path and "get" in paths.get(resolved_path, set())),
                "write_api_available": bool(
                    resolved_path and paths.get(resolved_path, set()) & {"post", "patch", "put"}
                ),
                "request_schema_available": request_schema_available,
                "response_schema_available": response_schema_available,
                "organization_scope_supported": organization_scope_supported,
                "organization_scope_field": organization_scope_field,
                "authentication_required": _authentication_required(operation),
                "idempotency_supported": method in {"post", "patch", "put"},
                "read_after_write_supported": _read_after_write_supported(paths, resolved_path or endpoint),
                "cleanup_supported": cleanup_supported,
                "cleanup_api_available": cleanup_supported,
                "status": status,
                "error_code": error_code,
                "endpoint": endpoint,
                "notes": _notes(status, public_api_available, organization_scope_supported, requirement),
            }
        )
    return matrix, paths


def has_capability(matrix: list[dict[str, Any]], capability: str) -> bool:
    return any(item["capability"] == capability and item["status"] in {"AVAILABLE", "PARTIAL"} for item in matrix)


def get_capability(matrix: list[dict[str, Any]], capability: str) -> dict[str, Any] | None:
    for item in matrix:
        if item.get("capability") == capability:
            return item
    return None


def _extract_paths(openapi: Any) -> dict[str, set[str]]:
    if not isinstance(openapi, dict):
        return {}
    paths: dict[str, set[str]] = {}
    for path, operations in (openapi.get("paths") or {}).items():
        if isinstance(operations, dict):
            paths[path] = {
                method.lower() for method in operations if method.lower() in {"get", "post", "patch", "put", "delete"}
            }
    return paths


def normalize_openapi_path(path: str) -> str:
    if not path:
        return "/"
    clean = f"/{path.strip('/')}"
    while "//" in clean:
        clean = clean.replace("//", "/")
    if clean != "/api" and clean.startswith("/api/api/"):
        clean = clean.removeprefix("/api")
    return clean


def resolve_openapi_operation(
    openapi: Any,
    requested_path: str,
    method: str,
    base_url: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(openapi, dict):
        return None, None
    openapi_paths = openapi.get("paths") if isinstance(openapi.get("paths"), dict) else {}
    candidates = _candidate_paths(requested_path, base_url)
    for candidate in candidates:
        if candidate in openapi_paths:
            operation = openapi_paths[candidate].get(method)
            return candidate, operation if isinstance(operation, dict) else None
    normalized_paths = {normalize_openapi_path(path): path for path in openapi_paths}
    for candidate in candidates:
        resolved = normalized_paths.get(candidate)
        if resolved is not None:
            operation = openapi_paths[resolved].get(method)
            return resolved, operation if isinstance(operation, dict) else None
    return None, None


def _candidate_paths(requested_path: str, base_url: str | None) -> list[str]:
    normalized = normalize_openapi_path(requested_path)
    parsed = urlparse(base_url or "")
    base_path = normalize_openapi_path(parsed.path or "")
    candidates = [normalized]
    if base_path != "/":
        candidates.append(normalize_openapi_path(f"{base_path}/{normalized.lstrip('/')}"))
    if normalized.startswith("/api/"):
        candidates.append(normalize_openapi_path(normalized.removeprefix("/api")))
    else:
        candidates.append(normalize_openapi_path(f"/api/{normalized.lstrip('/')}"))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _schema_available(operation: dict[str, Any], method: str, key: str, endpoint: str) -> bool:
    if endpoint == "/openapi.json":
        return True
    if key == "requestBody":
        return bool(operation.get("requestBody")) or method == "get"
    return bool(operation.get(key))


def _response_schema_available(operation: dict[str, Any], endpoint: str) -> bool:
    if endpoint == "/openapi.json":
        return True
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    return any("content" in response for response in responses.values() if isinstance(response, dict))


def _resolve_schema_ref(openapi: Any, schema: Any) -> dict[str, Any]:
    if not isinstance(openapi, dict) or not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    current: Any = openapi
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(current, dict):
            return {}
        current = current.get(part)
    return current if isinstance(current, dict) else {}


def _schema_has_property(openapi: Any, schema: Any, field_name: str) -> bool:
    resolved = _resolve_schema_ref(openapi, schema)
    properties = resolved.get("properties") if isinstance(resolved.get("properties"), dict) else {}
    if field_name in properties:
        return True
    all_of = resolved.get("allOf") if isinstance(resolved.get("allOf"), list) else []
    any_of = resolved.get("anyOf") if isinstance(resolved.get("anyOf"), list) else []
    one_of = resolved.get("oneOf") if isinstance(resolved.get("oneOf"), list) else []
    return any(_schema_has_property(openapi, item, field_name) for item in [*all_of, *any_of, *one_of])


def _request_json_schema(operation: dict[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody") if isinstance(operation.get("requestBody"), dict) else {}
    content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
    json_content = content.get("application/json") if isinstance(content.get("application/json"), dict) else {}
    schema = json_content.get("schema") if isinstance(json_content.get("schema"), dict) else {}
    return schema


def _organization_scope_contract(openapi: Any, operation: dict[str, Any]) -> tuple[bool, str | None]:
    parameters = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
    if any(parameter.get("name") == "organization_id" for parameter in parameters if isinstance(parameter, dict)):
        return True, "organization_id"
    schema = _request_json_schema(operation)
    if _schema_has_property(openapi, schema, "organization_id"):
        return True, "organization_id"
    return False, None


def _authentication_required(operation: dict[str, Any]) -> bool:
    return bool(operation.get("security"))


def _read_after_write_supported(paths: dict[str, set[str]], endpoint: str) -> bool:
    if "get" in paths.get(endpoint, set()):
        return True
    if endpoint.endswith("s"):
        return "get" in paths.get(f"{endpoint}/{{id}}", set())
    return any(path.startswith(endpoint.rstrip("/")) and "get" in methods for path, methods in paths.items())


def _capability_status(
    *,
    public_api_available: bool,
    request_schema_available: bool,
    response_schema_available: bool,
    organization_scope_supported: bool,
    requirement: dict[str, Any],
) -> str:
    if not public_api_available:
        return "CAPABILITY_MISSING"
    if requirement["capability"] == "enterprise_search" and not organization_scope_supported:
        return "PARTIAL"
    if not request_schema_available or not response_schema_available:
        return "PARTIAL"
    return "AVAILABLE"


def _error_code_for_status(
    status: str,
    public_api_available: bool,
    organization_scope_supported: bool,
    requirement: dict[str, Any],
) -> str | None:
    if not public_api_available:
        return "REQUIRED_ENDPOINT_NOT_AVAILABLE"
    if requirement["capability"] == "enterprise_search" and not organization_scope_supported:
        return "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE"
    if status == "PARTIAL":
        return "PUBLIC_READ_API_NOT_AVAILABLE"
    return None


def _notes(
    status: str,
    public_api_available: bool,
    organization_scope_supported: bool,
    requirement: dict[str, Any],
) -> str:
    if not public_api_available:
        return "required public endpoint not found in OpenAPI contract"
    if requirement["capability"] == "enterprise_search" and not organization_scope_supported:
        return "enterprise search exists but does not expose an organization-scoped public contract"
    if status == "PARTIAL":
        return "public endpoint exists but contract metadata is incomplete"
    return ""


def _cleanup_available(paths: dict[str, set[str]], endpoint: str) -> bool:
    if "delete" in paths.get(endpoint, set()):
        return True
    if endpoint.endswith("s"):
        item_endpoint = f"{endpoint}/{{id}}"
        return "delete" in paths.get(item_endpoint, set())
    return any(path.startswith(endpoint.rstrip("/")) and "delete" in methods for path, methods in paths.items())
