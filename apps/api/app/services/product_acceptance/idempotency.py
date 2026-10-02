from __future__ import annotations

from typing import Any

from app.services.product_acceptance.error_codes import error_payload

RESOURCE_GATE_MAP = {
    "organization": "organization_idempotent",
    "document_record": "document_idempotent",
    "document_version": "document_version_idempotent",
    "artifact": "storage_idempotent",
    "document_lifecycle": "processing_idempotent",
    "collection": "knowledge_idempotent",
    "conversation": "assistant_response_idempotent",
}


def build_idempotency_report(
    resources_before: dict[str, dict[str, Any]],
    resources_after: dict[str, dict[str, Any]],
    counts_before: dict[str, int],
    counts_after: dict[str, int],
) -> dict[str, Any]:
    resource_results: list[dict[str, Any]] = []
    count_deltas = {
        key: counts_after[key] - before_count
        for key, before_count in counts_before.items()
        if before_count >= 0 and counts_after.get(key, -1) >= 0
    }
    inventory_changed = any(delta != 0 for delta in count_deltas.values())
    duplicate_assets_detected = inventory_changed
    for resource_type, before in resources_before.items():
        if resource_type not in RESOURCE_GATE_MAP:
            continue
        after = resources_after.get(resource_type, {})
        external_ref = str(before.get("external_ref") or _external_ref(before) or resource_type)
        before_id = _resource_id(before)
        after_id = _resource_id(after)
        duplicate_count = _duplicate_count(before, after)
        duplicated = bool(duplicate_count > 0 or (before_id and after_id and before_id != after_id))
        duplicate_assets_detected = duplicate_assets_detected or duplicated
        resource_results.append(
            {
                "resource_type": resource_type,
                "external_ref": external_ref,
                "resource_id_before": before_id,
                "resource_id_after": after_id,
                "same_resource_reused": bool(before_id and before_id == after_id),
                "duplicate_count": duplicate_count,
                "duplicated": duplicated,
                "gate_code": RESOURCE_GATE_MAP[resource_type],
            }
        )
    return {
        "verified": bool(resource_results) and not duplicate_assets_detected,
        "duplicate_assets_detected": duplicate_assets_detected,
        "resources": resource_results,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "count_deltas": count_deltas,
        "inventory_changed": inventory_changed,
    }


def idempotency_gate_results(report: dict[str, Any]) -> list[dict[str, Any]]:
    by_gate = {item["gate_code"]: item for item in report.get("resources", []) if item.get("gate_code")}
    gates: list[dict[str, Any]] = []
    for resource_type, gate_code in RESOURCE_GATE_MAP.items():
        item = by_gate.get(gate_code)
        if item is None:
            gates.append(
                {
                    "gate_code": gate_code,
                    "status": "CAPABILITY_MISSING",
                    **error_payload("PUBLIC_READ_API_NOT_AVAILABLE"),
                    "details": {"resource_type": resource_type, "verification_available": False},
                }
            )
            continue
        item = {
            **item,
            "inventory_changed": bool(report.get("inventory_changed")),
            "count_deltas": report.get("count_deltas") or {},
        }
        if item.get("duplicated") or item["inventory_changed"] or not item.get("same_resource_reused"):
            gates.append(
                {
                    "gate_code": gate_code,
                    "status": "FAILED",
                    **error_payload("IDEMPOTENCY_VIOLATION"),
                    "details": item,
                }
            )
        else:
            gates.append({"gate_code": gate_code, "status": "PASSED", "details": item})
    return gates


def _resource_id(item: dict[str, Any]) -> str | None:
    for key in (
        "id",
        "resource_id",
        "document_record_id",
        "document_version_id",
        "artifact_id",
        "assistant_id",
        "conversation_id",
        "assistant_response_id",
    ):
        if item.get(key):
            return str(item[key])
    return None


def _external_ref(item: dict[str, Any]) -> str | None:
    for key in ("external_ref", "external_reference"):
        if item.get(key):
            return str(item[key])
    config = item.get("config") if isinstance(item.get("config"), dict) else {}
    if config.get("external_ref"):
        return str(config["external_ref"])
    return None


def _duplicate_count(before: dict[str, Any], after: dict[str, Any]) -> int:
    for item in (after, before):
        value = item.get("duplicate_count")
        if isinstance(value, int):
            return value
    return 0
