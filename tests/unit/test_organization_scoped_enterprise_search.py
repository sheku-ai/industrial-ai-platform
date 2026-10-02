from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function(path: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    module = ast.parse(_source(path))
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def test_enterprise_search_request_contract_accepts_organization_id() -> None:
    source = _source("apps/api/app/schemas/documents.py")

    assert "class EnterpriseSearchProductRequest" in source
    assert "organization_id: uuid.UUID | None = None" in source


def test_enterprise_search_route_forwards_organization_scope_to_filters() -> None:
    route = ast.unparse(_function("apps/api/app/api/routes/enterprise_search.py", "search_enterprise"))

    assert "context: RuntimeRequestContext" in route
    assert "context.organization_id is None" in route
    assert "context.has_permission('knowledge_collections', 'read')" in route
    assert "'organization_id': str(context.organization_id)" in route
    assert "payload.organization_id" not in route
    assert "build_enterprise_search(" in route


def test_repository_fts_sql_filters_by_document_record_organization() -> None:
    source = _source("apps/api/app/repositories/knowledge_index.py")
    module = ast.parse(source)
    document_imports = {
        alias.name
        for node in module.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.models.documents"
        for alias in node.names
    }
    search_fts = ast.unparse(_function("apps/api/app/repositories/knowledge_index.py", "search_fts"))

    assert {"DocumentRecord", "DocumentVersion"}.issubset(document_imports)
    assert "KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String)" in search_fts
    assert "KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String)" in search_fts
    assert "DocumentRecord.organization_id == organization_uuid" in search_fts
    assert "str(record.organization_id)" in search_fts


def test_processing_chunk_publication_preserves_document_lineage() -> None:
    handoff_source = _source("apps/api/app/services/document_processing_handoff.py")
    processing_source = _source("apps/api/app/services/document_processing_runtime.py")
    chunk_source = _source("apps/api/app/services/document_chunk_runtime.py")
    publication_source = _source("apps/api/app/services/knowledge_publication_runtime.py")

    assert '"document_record_id": _source_value(storage_execution_status, "document_record_id")' in handoff_source
    assert '"document_version_id": _source_value(storage_execution_status, "document_version_id")' in handoff_source
    assert '"document_record_id": source_summary.get("document_record_id")' in processing_source
    assert 'document_record_id=processing_result.get("document_record_id")' in chunk_source
    assert 'document_record_id=chunk.get("document_record_id")' in publication_source
    assert 'or chunk_result.get("document_record_id")' in publication_source


def test_knowledge_index_blocks_success_without_lineage() -> None:
    source = _source("apps/api/app/services/knowledge_index_runtime.py")
    lifecycle_source = _source("apps/api/app/services/document_lifecycle_orchestrator.py")

    assert "def validate_publication_lineage" in source
    assert '"code": "RESOURCE_LINEAGE_INCOMPLETE"' in source
    assert "db.get(DocumentRecord, record_uuid)" in source
    assert "db.get(DocumentVersion, version_uuid)" in source
    assert "lineage_complete" in lifecycle_source
    assert "knowledge_lineage_complete" in lifecycle_source


def test_enterprise_search_runtime_requires_existing_organization_scope() -> None:
    source = _source("apps/api/app/services/enterprise_search_runtime.py")

    assert '"organization_scope_required"' in source
    assert '"organization_scope_invalid"' in source
    assert '"organization_scope_not_found"' in source
    assert "db.get(Organization, organization_uuid) is None" in source
    assert "repository.indexed_chunk_count(organization_id=organization_id)" in source


def test_knowledge_fts_runtime_passes_organization_scope_to_repository() -> None:
    source = _source("apps/api/app/services/knowledge_fts_runtime.py")

    assert 'organization_id = search_filters.get("organization_id")' in source
    assert "indexed_chunk_count(organization_id=organization_id)" in source
    assert "organization_id=organization_id" in source
    assert '"organization_id": result.organization_id' in source


def test_assistant_search_inherits_organization_scope_from_retrieval_metadata() -> None:
    source = _source("apps/api/app/services/assistant_search_execution_runtime.py")

    assert "def _organization_id_from_search_context" in source
    assert "retrieval_plan.runtime_metadata" in source
    assert "scoped_search_config = _scoped_search_config" in source
    assert "search_config=scoped_search_config" in source


def test_chat_runtime_passes_organization_scope_into_assistant_search_config() -> None:
    source = _source("apps/api/app/services/chat_runtime.py")

    assert "def _scoped_search_config" in source
    assert 'filters.setdefault("organization_id", str(organization_id))' in source
    assert 'persisted_context.get("organization_id")' in source
    assert 'trace_metadata.get("organization_id")' in source


def test_document_processing_search_resolves_scope_from_artifact_or_handoff() -> None:
    source = _source("apps/api/app/services/document_processing_runtime.py")

    assert "def _organization_id_from_processing_context" in source
    assert "db.get(Artifact, uuid.UUID(str(artifact_id)))" in source
    assert "_scoped_search_config(search_config, organization_id)" in source


def test_hybrid_search_passes_metadata_organization_scope_to_enterprise_search() -> None:
    source = _source("apps/api/app/services/hybrid_search_runtime.py")

    assert "def _organization_id_from_metadata" in source
    assert 'search_config={"filters": {"organization_id": organization_id}}' in source


def test_product_acceptance_uses_real_scoped_search_and_chat_scope() -> None:
    source = _source("apps/api/app/services/product_acceptance/runtime.py")
    isolation_source = _source("apps/api/app/services/product_acceptance/isolation.py")

    assert '"/enterprise-search/search"' in source
    assert '"organization_id": org_id' in source
    assert '"runtime_context": {"organization_id": self._resource_id("organization")}' in source
    assert '"organization_id": probe_organization_id' in isolation_source
    assert "CROSS_ORGANIZATION_ACCESS_DETECTED" in isolation_source
    assert '"organization_id": source_organization_id' in isolation_source
    assert "positive_result_count" in isolation_source
    assert "negative_results_from_org_a" in isolation_source


def test_openapi_capability_discovery_resolves_request_body_refs() -> None:
    source = _source("apps/api/app/services/product_acceptance/capabilities.py")

    assert "def _resolve_schema_ref" in source
    assert "def _schema_has_property" in source
    assert "def _organization_scope_contract" in source
    assert '"organization_scope_field": organization_scope_field' in source


def test_assistant_response_public_read_includes_scope_and_conversation() -> None:
    route_source = ast.unparse(_function("apps/api/app/api/routes/assistants.py", "get_assistant_response"))
    service_source = _source("apps/api/app/services/assistant_response_runtime.py")
    repository_source = _source("apps/api/app/repositories/assistant.py")

    assert "context: RuntimeRequestContext" in route_source
    assert "_authorize_artifact(" in route_source
    assert "organization_id=str(context.organization_id) if context.organization_id else None" in route_source
    assert "organization_id: str | None" not in route_source
    assert "def _response_conversation_context" in service_source
    assert '"conversation_id": str(conversation.conversation_id)' in service_source
    assert '"turn_id": str(turn.conversation_turn_id)' in service_source
    assert '"organization_id": str(conversation.organization_id)' in service_source
    assert "record.organization_id" in service_source
    assert "turn.organization_id" in service_source
    assert '"RESOURCE_LINEAGE_INCOMPLETE"' in service_source
    assert '"CROSS_ORGANIZATION_ACCESS_DETECTED"' in service_source
    assert 'model.ownership_scope != "legacy_unscoped"' in repository_source


def test_product_acceptance_functional_errors_are_not_contract_invalid_for_search_and_chat() -> None:
    source = _source("apps/api/app/services/product_acceptance/runtime.py")
    idempotency_source = _source("apps/api/app/services/product_acceptance/idempotency.py")

    assert "def _functional_error_from_response" in source
    assert '"enterprise_search_query"' in source
    assert '"conversation_turn_created"' in source
    assert '"RESOURCE_LINEAGE_INCOMPLETE"' in source
    assert '"assistant_response_id"' in source
    assert '"conversation_id"' in idempotency_source
    assert '"assistant_response_id"' in idempotency_source
