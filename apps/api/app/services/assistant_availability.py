from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from app.models.ai import KnowledgeSource
from app.models.assistant_runtime import AssistantDefinition
from app.services.data_classification import classify_persisted_metadata, is_visible_product_data
from app.services.runtime_resolver import RuntimeResolution

ENABLED_ASSISTANT_STATUSES = {"active", "prepared"}
SEARCH_MODES = {"enterprise_search", "hybrid_search", "semantic_search"}


def has_validation_marker(metadata: dict[str, Any] | None) -> bool:
    return classify_persisted_metadata(metadata or {}) == "validation"


def operational_knowledge_sources(sources: Iterable[KnowledgeSource]) -> list[KnowledgeSource]:
    return [source for source in sources if is_visible_product_data(source.config)]


def _reference_values(value: Any) -> set[str]:
    if isinstance(value, dict):
        references: set[str] = set()
        for nested in value.values():
            references.update(_reference_values(nested))
        return references
    if isinstance(value, list):
        references = set()
        for nested in value:
            references.update(_reference_values(nested))
        return references
    return {str(value)} if value is not None else set()


def _assigned_sources(
    assistant: AssistantDefinition,
    sources: list[KnowledgeSource],
) -> list[KnowledgeSource]:
    metadata = assistant.runtime_metadata or {}
    explicit_references = _reference_values(
        {
            "knowledge_source_ids": metadata.get("knowledge_source_ids"),
            "knowledge_sources": metadata.get("knowledge_sources"),
            "collection_ids": metadata.get("collection_ids"),
        }
    )
    agent_reference = metadata.get("agent_id")
    return [
        source
        for source in sources
        if str(source.id) in explicit_references
        or str(source.collection_id) in explicit_references
        or (agent_reference is not None and str(source.agent_id) == str(agent_reference))
    ]


def _has_explicit_source_assignment(assistant: AssistantDefinition) -> bool:
    metadata = assistant.runtime_metadata or {}
    return bool(
        _reference_values(
            {
                "knowledge_source_ids": metadata.get("knowledge_source_ids"),
                "knowledge_sources": metadata.get("knowledge_sources"),
                "collection_ids": metadata.get("collection_ids"),
                "agent_id": metadata.get("agent_id"),
            }
        )
    )


def _source_matches_assistant_scope(source: KnowledgeSource, assistant: AssistantDefinition) -> bool:
    if assistant.ownership_scope == "organization":
        return assistant.organization_id is not None and source.organization_id == assistant.organization_id
    if assistant.ownership_scope == "global":
        return source.organization_id is None
    return False


def evaluate_assistant_availability(
    assistant: AssistantDefinition,
    *,
    organization_sources: Iterable[KnowledgeSource],
    searchable_collection_ids: set[UUID],
    runtime_resolution: RuntimeResolution,
    authorized: bool,
) -> dict[str, Any]:
    sources = [
        source
        for source in operational_knowledge_sources(organization_sources)
        if _source_matches_assistant_scope(source, assistant)
    ]
    assigned_sources = _assigned_sources(assistant, sources)
    available_sources = [
        source
        for source in sources
        if source.collection_id is not None and str(source.status or "").lower() in {"active", "ready", "prepared"}
    ]
    search_requested = assistant.default_search_mode in SEARCH_MODES
    enabled = assistant.assistant_status in ENABLED_ASSISTANT_STATUSES
    provider_required = bool(
        (assistant.runtime_metadata or {}).get("provider_required")
        or (assistant.runtime_metadata or {}).get("ai_required")
    )
    provider_configured = bool(runtime_resolution.provider_configured)
    generation_available = bool(runtime_resolution.generation_allowed)
    searchable_sources = [
        source for source in available_sources if source.collection_id in searchable_collection_ids
    ]
    assigned_searchable_sources = [
        source for source in assigned_sources if source.collection_id in searchable_collection_ids
    ]
    explicit_source_assignment = _has_explicit_source_assignment(assistant)
    implicit_organization_scope = bool(
        assistant.ownership_scope == "organization"
        and assistant.organization_id is not None
        and not explicit_source_assignment
    )
    knowledge_scope_valid = bool(
        assigned_searchable_sources or (implicit_organization_scope and searchable_sources)
    )
    enterprise_search_available = bool(searchable_sources)
    searchable_source_count = len(searchable_sources)
    grounded_answers_available = bool(
        enabled
        and authorized
        and search_requested
        and enterprise_search_available
        and knowledge_scope_valid
    )

    if not authorized:
        status, label, reason = "unauthorized", "Access required", "Assistant access is not authorized."
    elif str(assistant.assistant_status or "").lower() == "disabled":
        status, label, reason = "disabled", "Disabled", "The assistant is disabled."
    elif not enabled:
        status, label, reason = "not_configured", "Not configured", "The assistant is not enabled."
    elif search_requested and not grounded_answers_available:
        status, label, reason = (
            "needs_searchable_knowledge",
            "Needs searchable knowledge",
            "No searchable organization source is currently available for grounded answers.",
        )
    elif provider_required and not generation_available:
        status, label, reason = (
            "needs_ai_provider",
            "Needs AI provider",
            "This assistant requires an AI provider, but no executable provider is configured.",
        )
    elif grounded_answers_available:
        status, label, reason = (
            "ready_for_grounded_answers",
            "Ready for grounded answers",
            "Enterprise Search and searchable organization knowledge are available.",
        )
    elif generation_available:
        status, label, reason = (
            "available_for_general_assistance",
            "Available for general assistance",
            "An AI provider is configured and knowledge search is not required.",
        )
    else:
        status, label, reason = (
            "ready_without_ai_provider",
            "Ready without AI provider",
            "The configured runtime can operate without an external AI provider.",
        )

    return {
        "status": status,
        "label": label,
        "reason": reason,
        "assistant_enabled": enabled,
        "organization_access_authorized": authorized,
        "assigned_knowledge_source_count": len(assigned_sources),
        "assigned_knowledge_source_ids": [str(source.id) for source in assigned_sources],
        "assigned_searchable_source_count": len(assigned_searchable_sources),
        "available_organization_source_count": len(available_sources),
        "searchable_organization_source_count": searchable_source_count,
        "knowledge_scope_type": (
            "assigned_sources"
            if assigned_sources
            else "organization"
            if implicit_organization_scope
            else "unavailable"
        ),
        "knowledge_scope_valid": knowledge_scope_valid,
        "enterprise_search_requested": search_requested,
        "enterprise_search_available": enterprise_search_available,
        "grounded_answers_available": grounded_answers_available,
        "ai_provider_configured": provider_configured,
        "ai_provider_required": provider_required,
        "ai_generation_available": generation_available,
        "operation_without_llm_available": not provider_required,
        "operation_without_knowledge_available": True,
        "no_knowledge_behavior": "no_evidence_response" if search_requested else "general_assistance",
    }


def build_ai_capability_contract(
    *,
    enterprise_search_available: bool,
    assistant_availabilities: Iterable[dict[str, Any]],
    runtime_resolution: RuntimeResolution,
    historical_llm_execution_count: int,
) -> dict[str, Any]:
    availabilities = list(assistant_availabilities)
    grounded_ready = any(item.get("grounded_answers_available") is True for item in availabilities)
    generative_ready = bool(
        runtime_resolution.generation_allowed
        and runtime_resolution.provider_configured
        and runtime_resolution.model_configured
        and runtime_resolution.runtime_profile_id is not None
    )
    return {
        "deterministic_search": {
            "status": "available" if enterprise_search_available else "unavailable",
            "available": enterprise_search_available,
            "reason": (
                "PostgreSQL Enterprise Search has searchable governed knowledge."
                if enterprise_search_available
                else "No searchable governed knowledge is currently available."
            ),
            "requires_llm": False,
        },
        "grounded_assistant": {
            "status": "ready" if grounded_ready else "not_ready",
            "ready": grounded_ready,
            "reason": (
                "At least one enabled assistant has an applicable searchable knowledge scope."
                if grounded_ready
                else "No enabled assistant currently has an applicable searchable knowledge scope."
            ),
        },
        "generative_llm": {
            "status": "ready" if generative_ready else "not_configured",
            "ready": generative_ready,
            "reason": (
                "An enabled provider, model and applicable runtime profile are configured."
                if generative_ready
                else "No complete enabled generative provider and model association is currently configured."
            ),
            "provider_configured": bool(runtime_resolution.provider_configured),
            "model_configured": bool(runtime_resolution.model_configured),
            "runtime_profile_configured": runtime_resolution.runtime_profile_id is not None,
        },
        "historical_usage": {
            "llm_execution_count": max(int(historical_llm_execution_count), 0),
            "historical_executions_exist": historical_llm_execution_count > 0,
            "enables_current_configuration": False,
        },
    }
