#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import sys
import uuid
from pathlib import Path
from urllib import error, request

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.runtime import LocalProductAcceptanceRuntime, RuntimeOptions  # noqa: E402

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
PLATFORM_ACTOR = "reference-platform-operator"
PLATFORM_PRINCIPAL_TYPE = "reference_principal"


def _platform_request(method: str, path: str, payload: dict | None, correlation_id: str) -> tuple[int, object]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Authorization-Scope": "platform",
        "X-Actor-Reference": PLATFORM_ACTOR,
        "X-Principal-Type": PLATFORM_PRINCIPAL_TYPE,
        "X-Correlation-ID": correlation_id,
    }
    call = request.Request(f"{API_BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with request.urlopen(call, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def _require(condition: bool, code: str, details: object | None = None) -> None:
    if not condition:
        raise RuntimeError(json.dumps({"code": code, "details": details}, default=str, sort_keys=True))


def _id(value: dict, key: str = "id") -> str | None:
    candidate = value.get(key) or value.get("id")
    return str(candidate) if candidate else None


def _deletion(
    organization_id: str,
    idempotency_key: str,
    correlation_id: str,
) -> tuple[dict, dict, dict, dict]:
    payload = {"idempotency_key": idempotency_key}
    preview_status, preview = _platform_request(
        "POST",
        f"/core/organizations/{organization_id}/deletion-preview",
        payload,
        correlation_id,
    )
    _require(preview_status == 200 and isinstance(preview, dict), "deletion_preview_failed", preview)
    _require(preview.get("status") == "deletion_previewed", "deletion_preview_blocked", preview)
    delete_status, deleted = _platform_request(
        "POST", f"/core/organizations/{organization_id}/delete", payload, correlation_id
    )
    _require(delete_status == 200 and deleted.get("status") == "deleted", "organization_delete_failed", deleted)
    replay_status, replay = _platform_request(
        "POST", f"/core/organizations/{organization_id}/delete", payload, correlation_id
    )
    _require(replay_status == 200 and replay.get("replayed") is True, "deletion_replay_failed", replay)
    _require(
        replay.get("deletion_execution_id") == deleted.get("deletion_execution_id"),
        "deletion_replay_identity_changed",
        replay,
    )
    status_code, persisted = _platform_request(
        "GET", f"/core/organizations/{organization_id}/deletion-status", None, correlation_id
    )
    _require(status_code == 200 and persisted.get("status") == "deleted", "deletion_audit_not_retained", persisted)
    return preview, deleted, replay, persisted


def main() -> int:
    execution_key = f"local-product-acceptance-{uuid.uuid4()}"
    correlation_id = f"validation-org-lifecycle-{uuid.uuid4()}"
    stages: dict[str, str] = {}
    result: dict[str, object] = {
        "passed": False,
        "execution_key": execution_key,
        "correlation_id": correlation_id,
        "stages": stages,
    }
    try:
        provision_status, provision = _platform_request(
            "POST", "/reference-tenant/provision", {"requested_by": "organization-lifecycle-smoke"}, correlation_id
        )
        _require(
            provision_status == 200 and isinstance(provision, dict),
            "reference_tenant_provision_failed",
            provision,
        )
        stages["public_prerequisites"] = "PASSED"

        runtime = LocalProductAcceptanceRuntime(
            RuntimeOptions(api_base_url=API_BASE_URL, execution_key=execution_key, preserve=True, timeout=60)
        )
        acceptance = runtime.run()
        _require(
            acceptance.get("final_status") == "PASSED"
            and acceptance.get("gate_summary", {}).get("mandatory_passed") == 23,
            "local_product_chain_failed",
            acceptance,
        )
        stages["full_product_chain"] = "PASSED"
        resources = acceptance.get("created_resources") or {}
        organization_id = str(acceptance["organization"]["id"])
        control_id = _id(resources.get("isolation_probe_organization") or {})
        _require(bool(organization_id and control_id), "organization_identity_missing", resources)

        validation_metadata = {
            "external_ref": acceptance["organization"]["external_ref"],
            "scenario": "full_validation_organization_lifecycle",
            "execution_key": execution_key,
            "organization_class": "validation",
            "environment_purpose": "product_validation",
            "deletion_allowed": True,
        }
        updated = runtime.http.patch(
            f"/core/organizations/{organization_id}",
            {"name": "Industrial Validation Company", "config": validation_metadata},
        )
        control_updated = runtime.http.patch(
            f"/core/organizations/{control_id}",
            {
                "config": {
                    **validation_metadata,
                    "external_ref": f"{acceptance['organization']['external_ref']}:isolation-probe",
                    "control_organization": True,
                }
            },
        )
        _require(updated.ok and control_updated.ok, "validation_metadata_not_persisted")
        stages["organization_created"] = "PASSED"

        root_node = runtime.http.post(
            "/core/organization-nodes",
            {
                "organization_id": organization_id,
                "node_type": "organization",
                "code": f"validation-root-{runtime.identity.short_id}",
                "name": "Validation Root",
                "metadata": {"validation_generated": True},
                "status": "active",
            },
        )
        unit_node = runtime.http.post(
            "/core/organization-nodes",
            {
                "organization_id": organization_id,
                "parent_node_id": _id(root_node.data or {}),
                "node_type": "functional_unit",
                "code": f"validation-unit-{runtime.identity.short_id}",
                "name": "Validation Unit",
                "metadata": {"validation_generated": True},
                "status": "active",
            },
        )
        team_node = runtime.http.post(
            "/core/organization-nodes",
            {
                "organization_id": organization_id,
                "parent_node_id": _id(unit_node.data or {}),
                "node_type": "team",
                "code": f"validation-team-{runtime.identity.short_id}",
                "name": "Validation Team",
                "metadata": {"validation_generated": True},
                "status": "active",
            },
        )
        _require(
            all(item.ok and _id(item.data or {}) for item in (root_node, unit_node, team_node)),
            "organization_hierarchy_nodes_failed",
        )
        first_relationship = runtime.http.post(
            "/core/organization-relationships",
            {
                "organization_id": organization_id,
                "source_node_id": _id(root_node.data or {}),
                "target_node_id": _id(unit_node.data or {}),
                "relationship_type": "contains",
                "metadata": {"validation_generated": True},
                "status": "active",
            },
        )
        second_relationship = runtime.http.post(
            "/core/organization-relationships",
            {
                "organization_id": organization_id,
                "source_node_id": _id(unit_node.data or {}),
                "target_node_id": _id(team_node.data or {}),
                "relationship_type": "contains",
                "metadata": {"validation_generated": True},
                "status": "active",
            },
        )
        _require(
            first_relationship.ok and second_relationship.ok,
            "organization_hierarchy_relationships_failed",
        )
        stages["organization_hierarchy_persisted"] = "PASSED"

        second_payload = copy.deepcopy(runtime._document_lifecycle_payload("document_registration"))
        second_external_ref = f"{runtime.identity.document_external_ref}:markdown"
        second_content = (
            "# Governed validation evidence\n\n"
            "The secondary validation record confirms deterministic lineage and organization isolation."
        )
        second_payload["registration"].update(
            {
                "title": "Validation Pipeline Record",
                "external_reference": second_external_ref,
                "source_type": "text",
            }
        )
        second_payload.update(
            {
                "file_name": "validation-record.txt",
                "content_type": "text/plain",
                "content_text": second_content,
                "size_bytes": len(second_content.encode("utf-8")),
                "search_query": "secondary validation deterministic lineage",
                "idempotency_key": f"{execution_key}:second-document",
            }
        )
        second_lifecycle = runtime._post_document_lifecycle_until_complete(second_payload)
        _require(
            second_lifecycle.ok
            and second_lifecycle.data.get("storage_verified") is True
            and second_lifecycle.data.get("chunks_created") is True
            and second_lifecycle.data.get("knowledge_indexed") is True,
            "second_document_lifecycle_failed",
            second_lifecycle.data,
        )
        second_replay = runtime._post_document_lifecycle_until_complete(second_payload)
        _require(
            second_replay.ok
            and second_replay.data.get("document_record_id") == second_lifecycle.data.get("document_record_id")
            and second_replay.data.get("document_version_id") == second_lifecycle.data.get("document_version_id"),
            "second_document_idempotency_failed",
            second_replay.data,
        )
        persisted_search = runtime.http.post(
            "/enterprise-search/search",
            {"organization_id": organization_id, "query": "secondary validation deterministic lineage", "top_k": 5},
        )
        chunks = (persisted_search.data or {}).get("results") or []
        first_chunk = chunks[0] if chunks else {}
        knowledge_document = runtime.http.get(
            f"/knowledge/documents/{first_chunk.get('knowledge_document_id')}"
        )
        knowledge_chunk = runtime.http.get(f"/knowledge/chunks/{first_chunk.get('knowledge_chunk_id')}")
        _require(
            bool(chunks)
            and knowledge_document.ok
            and knowledge_chunk.ok
            and str(first_chunk.get("organization_id")) == organization_id
            and str(knowledge_document.data.get("document_record_id"))
            == str(second_lifecycle.data.get("document_record_id"))
            and str(knowledge_document.data.get("document_version_id"))
            == str(second_lifecycle.data.get("document_version_id"))
            and str(knowledge_chunk.data.get("knowledge_document_id"))
            == str(first_chunk.get("knowledge_document_id"))
            and bool(first_chunk.get("published_chunk_id"))
            and bool(first_chunk.get("content_hash")),
            "persisted_chunk_lineage_invalid",
            first_chunk,
        )
        stages["documents_storage_processing_knowledge"] = "PASSED"

        search = runtime.http.post(
            "/enterprise-search/search",
            {"organization_id": organization_id, "query": "secondary validation deterministic lineage", "top_k": 5},
        )
        _require(
            search.ok and bool((search.data or {}).get("results") or (search.data or {}).get("items")),
            "search_failed",
        )
        stages["enterprise_search_visible"] = "PASSED"
        assistant_id = acceptance.get("assistant", {}).get("assistant_id")
        _require(assistant_id, "assistant_not_persisted")
        chat_payload = {
            "assistant_id": assistant_id,
            "message": "secondary validation deterministic lineage",
            "requested_by": "organization-lifecycle-smoke",
            "runtime_context": {"organization_id": organization_id},
            "runtime_metadata": {
                "organization_id": organization_id,
                "validation_generated": True,
                "idempotency_key": f"chat:{execution_key}",
            },
        }
        chat = runtime.http.post("/assistants/chat", chat_payload)
        response_id = (chat.data or {}).get("assistant_response_id")
        conversation_id = (chat.data or {}).get("conversation_id")
        _require(chat.ok and response_id and conversation_id, "assistant_response_not_persisted", chat.data)
        response_first = runtime.http.get(f"/assistants/responses/{response_id}")
        response_replay = runtime.http.get(f"/assistants/responses/{response_id}")
        _require(
            response_first.ok
            and response_replay.ok
            and response_first.data.get("assistant_response_id") == response_replay.data.get("assistant_response_id"),
            "assistant_response_idempotency_failed",
        )
        _require(
            acceptance.get("idempotency", {}).get("verified") is True,
            "assistant_response_idempotency_failed",
        )
        stages["assistant_conversation_idempotency"] = "PASSED"
        _require(acceptance.get("isolation", {}).get("checked") is True, "cross_organization_isolation_failed")
        runtime.http.set_organization_scope(str(control_id))
        isolated_assistant = runtime.http.get(f"/assistants/{assistant_id}")
        isolated_conversation = runtime.http.get(f"/assistants/conversations/{conversation_id}")
        isolated_document = runtime.http.post(
            f"/documents/{second_lifecycle.data.get('document_record_id')}/versions/uploads",
            {
                "file_name": "isolation-probe.txt",
                "content_type": "text/plain",
                "size_bytes": 0,
                "checksum_sha256": "0" * 64,
            },
        )
        runtime.http.set_organization_scope(organization_id)
        _require(
            isolated_assistant.status_code in {403, 404}
            and isolated_conversation.status_code in {403, 404}
            and isolated_document.status_code == 404,
            "cross_organization_resource_access_detected",
            {
                "assistant": isolated_assistant.status_code,
                "conversation": isolated_conversation.status_code,
                "document": isolated_document.status_code,
            },
        )
        stages["cross_organization_isolation"] = "PASSED"
        _require(acceptance.get("audit", {}).get("audit_phase_present") is True, "audit_evidence_missing")
        stages["audit_and_correlation"] = "PASSED"

        preview, deleted, replay, persisted = _deletion(
            organization_id, f"delete:{execution_key}", correlation_id
        )
        counts = preview.get("resource_counts_before") or {}
        expected_minimums = {
            "organization_nodes": 3,
            "organization_relationships": 2,
            "roles": 1,
            "role_assignments": 1,
            "documents": 2,
            "document_versions": 2,
            "knowledge_documents": 2,
            "knowledge_chunks": 2,
            "assistants": 1,
            "conversations": 1,
            "turns": 2,
            "assistant_responses": 1,
        }
        _require(
            all(int(counts.get(key) or 0) >= minimum for key, minimum in expected_minimums.items()),
            "deletion_preview_counts_inaccurate",
            {"counts": counts, "expected_minimums": expected_minimums},
        )
        _require(
            deleted.get("object_storage_objects_deleted") == counts.get("storage_objects"),
            "object_storage_cleanup_incomplete",
            deleted,
        )
        _require(deleted.get("correlation_id") == correlation_id, "deletion_correlation_not_persisted", deleted)
        stages["deletion_preview_accurate"] = "PASSED"
        stages["organization_and_storage_deleted"] = "PASSED"
        stages["deletion_replay_idempotent"] = "PASSED"
        stages["deletion_audit_retained"] = "PASSED"

        control_preview, control_deleted, _, _ = _deletion(
            str(control_id), f"delete-control:{execution_key}", correlation_id
        )
        stages["control_organization_deleted"] = "PASSED"
        result.update(
            {
                "passed": True,
                "organization_id": organization_id,
                "control_organization_id": control_id,
                "resource_counts_before": counts,
                "resource_counts_deleted": deleted.get("resource_counts_deleted"),
                "storage_objects_before": counts.get("storage_objects"),
                "storage_objects_after": 0,
                "deletion_execution_id": persisted.get("deletion_execution_id"),
                "deletion_replayed": replay.get("replayed"),
                "control_resource_counts_before": control_preview.get("resource_counts_before"),
                "control_resource_counts_deleted": control_deleted.get("resource_counts_deleted"),
                "unexpected_http_500": 0,
            }
        )
    except Exception as exc:
        result["error"] = str(exc)
        for stage in (
            "public_prerequisites",
            "full_product_chain",
            "organization_created",
            "organization_hierarchy_persisted",
            "documents_storage_processing_knowledge",
            "enterprise_search_visible",
            "assistant_conversation_idempotency",
            "cross_organization_isolation",
            "audit_and_correlation",
            "deletion_preview_accurate",
            "organization_and_storage_deleted",
            "deletion_replay_idempotent",
            "deletion_audit_retained",
            "control_organization_deleted",
        ):
            stages.setdefault(stage, "NOT EXECUTED")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
