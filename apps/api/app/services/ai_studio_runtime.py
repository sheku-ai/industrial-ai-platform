from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.ai import Agent, Guardrail, KnowledgeSource, Model, Prompt, Provider, Workflow
from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantDefinition,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantResponse,
    AssistantRuntimeRun,
    AssistantSession,
)
from app.models.audit import AuditEvent
from app.models.runtime import RuntimePersistenceRecord
from app.repositories.knowledge_index import KnowledgeIndexRepository
from app.services.assistant_availability import (
    build_ai_capability_contract,
    evaluate_assistant_availability,
    operational_knowledge_sources,
)
from app.services.data_classification import is_visible_product_data
from app.services.runtime_resolver import ASSISTED, RuntimeResolverService

AI_STUDIO_RUNTIME_SCHEMA_VERSION = "1"
AI_STUDIO_RUNTIME_NAME = "ai_studio_runtime"
RECENT_LIMIT = 10
SECRET_KEY_FRAGMENTS = ("secret", "password", "token", "api_key", "apikey", "credential")
APPLICABLE_CONFIGURATION_MODELS = (
    Provider,
    Model,
    Prompt,
    Guardrail,
    Workflow,
    AssistantDefinition,
    Agent,
    KnowledgeSource,
)


def _count(db: Session, model: Any, *criteria: Any) -> int:
    primary_key = model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))
    statement = select(func.count(primary_key))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _scope_criteria(model: Any, organization_id: UUID | None, platform_scope: bool) -> tuple[Any, ...]:
    if platform_scope or organization_id is None or not hasattr(model, "organization_id"):
        return ()
    if model in {Provider, Model}:
        return (model.organization_id == organization_id,)
    if model in APPLICABLE_CONFIGURATION_MODELS:
        return (or_(model.organization_id == organization_id, model.organization_id.is_(None)),)
    return (model.organization_id == organization_id,)


def _scoped_rows(
    db: Session,
    model: Any,
    organization_id: UUID | None,
    platform_scope: bool,
    *order_by: Any,
) -> list[Any]:
    criteria = list(_scope_criteria(model, organization_id, platform_scope))
    if hasattr(model, "data_origin"):
        criteria.append(model.data_origin.in_(("operational", "reference")))
    if hasattr(model, "ownership_scope"):
        criteria.append(model.ownership_scope != "legacy_unscoped")
    statement = select(model).where(*criteria)
    if order_by:
        statement = statement.order_by(*order_by)
    rows = list(db.scalars(statement).all())
    return [
        row
        for row in rows
        if is_visible_product_data(
            getattr(row, "config", None),
            getattr(row, "configuration", None),
            getattr(row, "metadata_json", None),
            getattr(row, "runtime_metadata", None),
        )
    ]


def _count_by_status(rows: list[Any], status_attr: str) -> dict[str, int]:
    return dict(Counter(str(getattr(row, status_attr, None) or "unknown") for row in rows))


def _enabled(status: str | None, enabled: bool | None = None) -> bool:
    if enabled is not None:
        return bool(enabled)
    return str(status or "").lower() not in {"disabled", "failed", "archived", "deleted"}


def _readiness(status: str, blocking_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    issues = blocking_issues or []
    return {
        "status": "blocked" if issues else status,
        "blocking_issues": issues,
    }


def _contains_secret_marker(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(fragment in str(key).lower() for fragment in SECRET_KEY_FRAGMENTS) or _contains_secret_marker(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_marker(item) for item in value)
    return False


def _safe_preview(prompt: Prompt) -> str | None:
    metadata = prompt.metadata_json or {}
    restricted = bool(metadata.get("restricted") or metadata.get("sensitive") or metadata.get("confidential"))
    if restricted:
        return None
    source = prompt.template or prompt.content
    return source[:160] if source else None


def _references_payload(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for nested in value.values():
            references.update(_references_payload(nested))
    elif isinstance(value, list):
        for nested in value:
            references.update(_references_payload(nested))
    elif value is not None:
        references.add(str(value))
    return references


def _assignment_counts(
    assistants: list[AssistantDefinition],
    agents: list[Agent],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for agent in agents:
        for value in (agent.model_id, agent.prompt_id):
            if value:
                counts[str(value)] += 1
        for key, value in Counter(_references_payload(agent.config or {})).items():
            counts[str(key)] += value
    for assistant in assistants:
        metadata = assistant.runtime_metadata or {}
        profile = {
            "assistant_key": assistant.assistant_key,
            "model_profile": metadata.get("model_profile") or metadata.get("model") or {},
            "prompt_profile": metadata.get("prompt_profile") or metadata.get("prompt") or {},
            "guardrail_profile": assistant.guardrail_profile or {},
        }
        for reference in _references_payload(profile):
            counts[reference] += 1
    return counts


def _providers_payload(providers: list[Provider]) -> list[dict[str, Any]]:
    return [
        {
            "provider_id": provider.id,
            "organization_id": provider.organization_id,
            "provider_key": provider.provider_key,
            "provider_type": provider.provider_type,
            "adapter_type": provider.adapter_type,
            "display_name": provider.display_name,
            "status": provider.status,
            "enabled": provider.enabled,
            "configuration_present": bool(provider.configuration),
            "secrets_configured": _contains_secret_marker(provider.configuration or {}),
            "health_state": provider.health_state,
            "readiness": _readiness("ready" if provider.enabled else "pending"),
        }
        for provider in providers
    ]


def _models_payload(models: list[Model], providers_by_id: dict[Any, Provider]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for model in models:
        provider = providers_by_id.get(model.provider_id)
        diagnostics = []
        if model.provider_id and provider is None:
            diagnostics.append({"code": "provider_missing"})
        items.append(
            {
                "model_id": model.id,
                "organization_id": model.organization_id,
                "model_key": model.model_key or model.code,
                "code": model.code,
                "name": model.display_name or model.name,
                "provider": provider.provider_key if provider else model.provider,
                "model_type": model.model_type,
                "deployment_mode": (model.metadata_json or {}).get("deployment_mode")
                or (model.configuration or {}).get("deployment_mode"),
                "status": model.status,
                "enabled": model.enabled,
                "default_for": (model.metadata_json or {}).get("default_for") or [],
                "capabilities": model.capabilities or {},
                "readiness": _readiness("ready" if model.enabled and not diagnostics else "pending", diagnostics),
                "diagnostics": diagnostics,
                "provider_configuration": {
                    "provider_key": provider.provider_key if provider else model.provider,
                    "provider_type": provider.provider_type if provider else None,
                    "status": provider.status if provider else None,
                    "enabled": provider.enabled if provider else False,
                    "configuration_present": bool(provider.configuration) if provider else False,
                    "secrets_configured": _contains_secret_marker(provider.configuration or {}) if provider else False,
                },
            }
        )
    return items


def _prompts_payload(prompts: list[Prompt], assignment_counts: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for prompt in prompts:
        references = [str(prompt.id), prompt.prompt_key, prompt.code, prompt.name]
        assigned_count = sum(assignment_counts.get(str(reference), 0) for reference in references if reference)
        variables = prompt.variables or {}
        items.append(
            {
                "prompt_id": prompt.id,
                "prompt_key": prompt.prompt_key or prompt.code,
                "code": prompt.code,
                "name": prompt.display_name or prompt.name,
                "prompt_type": prompt.prompt_type,
                "version": prompt.version,
                "status": prompt.status,
                "enabled": prompt.enabled,
                "template_format": prompt.template_format,
                "variables_count": len(variables),
                "assigned_assistants_count": assigned_count,
                "workflow_usage_count": 0,
                "safe_preview": _safe_preview(prompt),
                "readiness": _readiness("ready" if prompt.enabled else "pending"),
            }
        )
    return items


def _guardrails_payload(guardrails: list[Guardrail], assignment_counts: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for guardrail in guardrails:
        references = [str(guardrail.id), guardrail.guardrail_key, guardrail.code, guardrail.name]
        assigned_count = sum(assignment_counts.get(str(reference), 0) for reference in references if reference)
        items.append(
            {
                "guardrail_id": guardrail.id,
                "guardrail_key": guardrail.guardrail_key or guardrail.code,
                "code": guardrail.code,
                "name": guardrail.display_name or guardrail.name,
                "guardrail_type": guardrail.guardrail_type,
                "enforcement_mode": guardrail.enforcement_mode,
                "status": guardrail.status,
                "enabled": guardrail.enabled,
                "policy_present": bool(guardrail.policy or guardrail.rules),
                "fallback_behavior": guardrail.fallback_behavior,
                "assigned_assistants_count": assigned_count,
                "readiness": _readiness("ready" if guardrail.enabled else "pending"),
                "diagnostics": [],
            }
        )
    return items


def _workflows_payload(workflows: list[Workflow], assignment_counts: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for workflow in workflows:
        definition = workflow.definition or {}
        steps = definition.get("steps") if isinstance(definition, dict) else []
        references = [str(workflow.id), workflow.code, workflow.name]
        assigned_count = sum(assignment_counts.get(str(reference), 0) for reference in references if reference)
        items.append(
            {
                "workflow_id": workflow.id,
                "workflow_key": workflow.code,
                "code": workflow.code,
                "name": workflow.name,
                "workflow_type": definition.get("workflow_type") if isinstance(definition, dict) else None,
                "status": workflow.status,
                "enabled": _enabled(workflow.status),
                "steps_count": len(steps) if isinstance(steps, list) else 0,
                "definition_present": bool(definition),
                "assigned_assistants_count": assigned_count,
                "readiness": _readiness("ready" if _enabled(workflow.status) and definition else "pending"),
                "diagnostics": [],
            }
        )
    return items


def _assistants_payload(
    assistants: list[AssistantDefinition],
    availability_by_assistant: dict[Any, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for assistant in assistants:
        metadata = assistant.runtime_metadata or {}
        availability = availability_by_assistant.get(assistant.assistant_id, {})
        items.append(
            {
                "assistant_id": assistant.assistant_id,
                "organization_id": assistant.organization_id,
                "ownership_scope": assistant.ownership_scope,
                "data_origin": assistant.data_origin,
                "assistant_key": assistant.assistant_key,
                "assistant_name": assistant.assistant_name,
                "assistant_status": assistant.assistant_status,
                "assistant_version": assistant.assistant_version,
                "assistant_type": assistant.assistant_type,
                "default_search_mode": assistant.default_search_mode,
                "allowed_runtime_domains": assistant.allowed_runtime_domains or [],
                "model_profile": metadata.get("model_profile") or metadata.get("model") or {},
                "prompt_profile": metadata.get("prompt_profile") or metadata.get("prompt") or {},
                "guardrail_profile": assistant.guardrail_profile or {},
                "assigned_knowledge_sources_count": availability.get("assigned_knowledge_source_count", 0),
                "searchable_organization_sources_count": availability.get(
                    "searchable_organization_source_count", 0
                ),
                "availability": availability,
                "readiness": {
                    "status": availability.get("status", "not_configured"),
                    "blocking_issues": [],
                },
            }
        )
    return items


def _knowledge_sources_payload(knowledge_sources: list[KnowledgeSource]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": source.id,
            "source_type": source.source_type,
            "collection_id": source.collection_id,
            "status": source.status,
            "enabled": _enabled(source.status),
            "configured": source.collection_id is not None,
            "assistant_binding": source.agent_id,
            "readiness": _readiness("ready" if _enabled(source.status) and source.collection_id else "pending"),
        }
        for source in knowledge_sources
    ]


def _runtime_executions(
    db: Session,
    organization_id: UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    llm_executions = _scoped_rows(db, AssistantLlmExecution, organization_id, platform_scope)
    citation_verifications = _scoped_rows(db, AssistantCitationVerification, organization_id, platform_scope)
    responses = _scoped_rows(db, AssistantResponse, organization_id, platform_scope)
    sessions = _scoped_rows(db, AssistantSession, organization_id, platform_scope)
    runs = _scoped_rows(db, AssistantRuntimeRun, organization_id, platform_scope)
    visible_prompt_packages = _scoped_rows(db, AssistantPromptPackage, organization_id, platform_scope)
    visible_invocation_plans = _scoped_rows(db, AssistantLlmInvocationPlan, organization_id, platform_scope)
    return {
        "prompt_assembly_executions": len(visible_prompt_packages),
        "llm_gateway_executions": len(visible_invocation_plans),
        "llm_execution_records": len(llm_executions),
        "citation_verification_executions": len(citation_verifications),
        "assistant_response_executions": len(responses),
        "assistant_sessions": len(sessions),
        "assistant_runtime_executions": len(runs),
        "chat_runtime_executions": (
            _count(
                db,
                RuntimePersistenceRecord,
                RuntimePersistenceRecord.runtime_domain == "chat_runtime",
            )
            if platform_scope
            else 0
        ),
        "llm_execution_by_status": _count_by_status(llm_executions, "execution_status"),
        "citation_verification_by_status": _count_by_status(citation_verifications, "verification_status"),
        "assistant_response_by_status": _count_by_status(responses, "response_status"),
        "assistant_sessions_by_status": _count_by_status(sessions, "session_status"),
        "assistant_runtime_by_status": _count_by_status(runs, "run_status"),
    }


def _audit_diagnostics(audit_events: list[AuditEvent], degraded_items: list[dict[str, Any]]) -> dict[str, Any]:
    ai_audit = [
        event
        for event in audit_events
        if str(event.resource_type or "").lower().startswith(("ai", "assistant", "prompt", "guardrail", "workflow"))
    ]
    recent_audit = sorted(ai_audit, key=lambda item: item.created_at, reverse=True)[:RECENT_LIMIT]
    return {
        "audit_events_count": len(ai_audit),
        "recent_audit_events": [
            {
                "audit_event_id": event.id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "created_at": event.created_at,
            }
            for event in recent_audit
        ],
        "blocking_issues": [],
        "warnings": [],
        "pending_capabilities": [],
        "degraded_items": degraded_items,
    }


def build_ai_studio_runtime(
    db: Session,
    organization_id: UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    providers = _scoped_rows(db, Provider, organization_id, platform_scope, Provider.provider_key.asc())
    models = _scoped_rows(db, Model, organization_id, platform_scope, Model.code.asc())
    prompts = _scoped_rows(db, Prompt, organization_id, platform_scope, Prompt.code.asc())
    guardrails = _scoped_rows(db, Guardrail, organization_id, platform_scope, Guardrail.code.asc())
    workflows = _scoped_rows(db, Workflow, organization_id, platform_scope, Workflow.code.asc())
    assistants = _scoped_rows(
        db,
        AssistantDefinition,
        organization_id,
        platform_scope,
        AssistantDefinition.assistant_key.asc(),
    )
    agents = _scoped_rows(db, Agent, organization_id, platform_scope, Agent.code.asc())
    knowledge_sources = operational_knowledge_sources(
        _scoped_rows(db, KnowledgeSource, organization_id, platform_scope)
    )
    audit_events = _scoped_rows(
        db,
        AuditEvent,
        organization_id,
        platform_scope,
        AuditEvent.created_at.desc(),
    )

    providers_by_id = {provider.id: provider for provider in providers}
    searchable_collection_ids = KnowledgeIndexRepository(db).indexed_collection_ids(
        organization_id=organization_id
    )
    runtime_resolution = RuntimeResolverService().resolve(
        db,
        organization_id=organization_id,
        requested_answer_mode=ASSISTED,
    )
    availability_by_assistant = {
        assistant.assistant_id: evaluate_assistant_availability(
            assistant,
            organization_sources=knowledge_sources,
            searchable_collection_ids=searchable_collection_ids,
            runtime_resolution=runtime_resolution,
            authorized=True,
        )
        for assistant in assistants
    }
    assignment_counts = _assignment_counts(assistants, agents)
    runtime_executions = _runtime_executions(db, organization_id, platform_scope)
    capability_availability = build_ai_capability_contract(
        enterprise_search_available=bool(searchable_collection_ids),
        assistant_availabilities=availability_by_assistant.values(),
        runtime_resolution=runtime_resolution,
        historical_llm_execution_count=runtime_executions["llm_execution_records"],
    )
    readiness_by_domain = {
        "models": bool(models),
        "providers": bool(providers),
        "prompts": bool(prompts),
        "guardrails": bool(guardrails),
        "workflows": bool(workflows),
        "assistants": bool(assistants),
        "knowledge_sources": bool(knowledge_sources),
        "deterministic_search": bool(capability_availability["deterministic_search"]["available"]),
        "grounded_assistant": bool(capability_availability["grounded_assistant"]["ready"]),
        "generative_llm": bool(capability_availability["generative_llm"]["ready"]),
    }
    degraded_items = [
        {"item_type": "domain", "item_id": key, "status": "pending"}
        for key, ready in readiness_by_domain.items()
        if not ready and key not in {"generative_llm"}
    ]
    ai_ready = bool(
        capability_availability["grounded_assistant"]["ready"]
        or capability_availability["generative_llm"]["ready"]
    )
    runtime_status = "ready" if ai_ready and bool(assistants) else "degraded"
    audit_diagnostics = _audit_diagnostics(audit_events, degraded_items)
    policy_readiness = {
        "ai_optional": True,
        "platform_works_without_ai": True,
        "llm_execution_disabled_when_not_configured": True,
        "qdrant_not_required": True,
        "embeddings_not_required": True,
        "readiness_by_domain": readiness_by_domain,
    }
    return {
        "ai_studio_runtime_schema_version": AI_STUDIO_RUNTIME_SCHEMA_VERSION,
        "runtime_name": AI_STUDIO_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "metric_scope": "platform" if platform_scope else "selected_organization",
            "organization_id": None if platform_scope else organization_id,
            "included_data_origins": ["platform"] if platform_scope else ["operational", "reference"],
            "runtime_status": runtime_status,
            "ai_ready": ai_ready,
            "assistants_ready": bool(assistants),
            "models_ready": bool(capability_availability["generative_llm"]["model_configured"]),
            "prompts_ready": bool(prompts),
            "guardrails_ready": bool(guardrails),
            "workflows_ready": bool(workflows),
            "knowledge_sources_ready": bool(capability_availability["grounded_assistant"]["ready"]),
            "deterministic_search_ready": bool(capability_availability["deterministic_search"]["available"]),
            "grounded_assistant_ready": bool(capability_availability["grounded_assistant"]["ready"]),
            "generative_llm_ready": bool(capability_availability["generative_llm"]["ready"]),
            "historical_llm_usage_present": bool(
                capability_availability["historical_usage"]["historical_executions_exist"]
            ),
            "postgresql_source_of_truth": True,
            "ai_required": False,
            "llm_used": False,
            "qdrant_used": False,
            "external_provider_calls": False,
        },
        "models_and_providers": {
            "models": _models_payload(models, providers_by_id),
            "providers": _providers_payload(providers),
        },
        "prompts": _prompts_payload(prompts, assignment_counts),
        "guardrails": _guardrails_payload(guardrails, assignment_counts),
        "workflows": _workflows_payload(workflows, assignment_counts),
        "assistants": _assistants_payload(assistants, availability_by_assistant),
        "knowledge_sources": _knowledge_sources_payload(knowledge_sources),
        "runtime_executions": runtime_executions,
        "capability_availability": capability_availability,
        "policy_readiness": policy_readiness,
        "audit_diagnostics": audit_diagnostics,
        "diagnostics": audit_diagnostics,
        "postgresql_source_of_truth": True,
        "ai_required": False,
        "llm_used": False,
        "qdrant_used": False,
        "external_provider_calls": False,
    }
