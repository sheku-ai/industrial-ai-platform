from __future__ import annotations

from typing import Any

from app.services.product_acceptance.error_codes import error_payload
from app.services.product_acceptance.gateway import AcceptanceHttpClient


def evaluate_search_isolation(
    client: AcceptanceHttpClient,
    capability: dict[str, Any] | None,
    source_organization_id: str | None,
    probe_organization_id: str | None,
    query: str,
) -> dict[str, Any]:
    if not capability or capability.get("status") == "CAPABILITY_MISSING":
        return _capability_missing("ENTERPRISE_SEARCH_CAPABILITY_NOT_AVAILABLE", {"capability": capability})
    if not capability.get("organization_scope_supported"):
        return _capability_missing(
            "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE",
            {"mandatory": True, "organization_scope_supported": False},
        )
    if not source_organization_id or not probe_organization_id:
        return _capability_missing(
            "ORGANIZATION_ISOLATION_NOT_VERIFIABLE",
            {
                "mandatory": True,
                "source_organization_id": source_organization_id,
                "probe_organization_id": probe_organization_id,
            },
        )

    positive_payload = {
        "query": query,
        "top_k": 5,
        "include_debug": True,
        "organization_id": source_organization_id,
    }
    positive = _post_in_organization_scope(client, source_organization_id, positive_payload)
    if not positive.ok:
        return _failed_search_response(
            positive,
            error_code="RESOURCE_LINEAGE_INCOMPLETE",
            query=query,
            scope=source_organization_id,
            reason="positive_query_failed",
        )
    positive_results = _search_results(positive.data)
    if not _query_processed(positive.data) or not positive_results:
        return {
            "status": "FAILED",
            **error_payload("ORGANIZATION_ISOLATION_NOT_VERIFIABLE"),
            "details": {
                "mandatory": True,
                "query_sent": query,
                "scope_sent": source_organization_id,
                "positive_query_processed": _query_processed(positive.data),
                "positive_result_count": len(positive_results),
                "response": positive.data,
                "reason": "positive_query_not_conclusive",
            },
        }
    positive_mismatches = [item for item in positive_results if _organization_id(item) != source_organization_id]
    if positive_mismatches:
        return {
            "status": "FAILED",
            **error_payload("CROSS_ORGANIZATION_ACCESS_DETECTED"),
            "details": {
                "mandatory": True,
                "query_sent": query,
                "scope_sent": source_organization_id,
                "positive_result_count": len(positive_results),
                "positive_mismatch_count": len(positive_mismatches),
            },
        }

    payload = {
        "query": query,
        "top_k": 5,
        "include_debug": True,
        "organization_id": probe_organization_id,
    }
    result = _post_in_organization_scope(client, probe_organization_id, payload)
    if not result.ok:
        return _failed_search_response(
            result,
            error_code="ORGANIZATION_ISOLATION_NOT_VERIFIABLE",
            query=query,
            scope=probe_organization_id,
            reason="negative_query_failed",
        )
    results = _search_results(result.data)
    if not _query_processed(result.data):
        return {
            "status": "FAILED",
            **error_payload("ORGANIZATION_ISOLATION_NOT_VERIFIABLE"),
            "details": {
                "mandatory": True,
                "query_sent": query,
                "scope_sent": probe_organization_id,
                "response": result.data,
                "reason": "query_not_processed",
            },
        }
    leaked = [item for item in results if _organization_id(item) == source_organization_id]
    if leaked:
        return {
            "status": "FAILED",
            **error_payload("CROSS_ORGANIZATION_ACCESS_DETECTED"),
            "details": {
                "mandatory": True,
                "query_sent": query,
                "scope_sent": probe_organization_id,
                "source_organization_id": source_organization_id,
                "leaked_result_count": len(leaked),
            },
        }
    return {
        "status": "PASSED",
        "details": {
            "mandatory": True,
            "query_sent": query,
            "scope_sent": probe_organization_id,
            "source_organization_id": source_organization_id,
            "positive_query_processed": True,
            "positive_result_count": len(positive_results),
            "positive_results_all_match_org_a": True,
            "negative_query_processed": True,
            "negative_results_from_org_a": 0,
            "result_count": len(results),
            "organization_scope_supported": True,
        },
    }


def _post_in_organization_scope(
    client: AcceptanceHttpClient,
    organization_id: str,
    payload: dict[str, Any],
) -> Any:
    setter = getattr(client, "set_organization_scope", None)
    if not callable(setter):
        return client.post("/enterprise-search/search", payload)

    original_scope = getattr(client, "authorization_scope", None)
    original_organization_id = getattr(client, "organization_id", None)
    setter(organization_id)
    try:
        return client.post("/enterprise-search/search", payload)
    finally:
        if original_scope == "organization" and original_organization_id:
            setter(str(original_organization_id))
        elif original_scope == "platform":
            client.set_platform_scope()
        else:
            client.authorization_scope = original_scope
            client.organization_id = original_organization_id


def _capability_missing(error_code: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "CAPABILITY_MISSING",
        **error_payload(error_code),
        "details": details,
    }


def _failed_search_response(
    result: Any,
    *,
    error_code: str,
    query: str,
    scope: str,
    reason: str,
) -> dict[str, Any]:
    status = "BLOCKED_BY_ENVIRONMENT" if result.status_code == 0 else "FAILED"
    return {
        "status": status,
        **error_payload(error_code),
        "details": {
            "mandatory": True,
            "query_sent": query,
            "scope_sent": scope,
            "status_code": result.status_code,
            "response": result.data,
            "error": result.error,
            "reason": reason,
        },
    }


def _search_results(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("results", "items", "chunks", "documents"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _organization_id(item: dict[str, Any]) -> str | None:
    for key in ("organization_id", "tenant_id"):
        if item.get(key):
            return str(item[key])
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if metadata.get("organization_id"):
        return str(metadata["organization_id"])
    return None


def _query_processed(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("query_processed") is True or data.get("search_executed") is True:
        return True
    if data.get("results") is not None or data.get("items") is not None:
        return True
    diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
    return bool(diagnostics.get("query_processed") or diagnostics.get("search_executed"))
