from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.ai_studio_runtime import build_ai_studio_runtime
from app.services.product_integration_runtime import build_product_integration_runtime

MODEL_PROVIDER_CENTER_RUNTIME_SCHEMA_VERSION = "1"
MODEL_PROVIDER_CENTER_RUNTIME_NAME = "model_provider_center_runtime"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique_by_persisted_identity(items: list[Any], identity_field: str) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        record = _mapping(item)
        identity = record.get(identity_field)
        if identity is None:
            unique.append(record)
            continue
        persisted_identity = (
            str(record.get("ownership_scope") or "unscoped"),
            str(record.get("organization_id") or "platform"),
            str(identity),
        )
        if persisted_identity in seen:
            continue
        seen.add(persisted_identity)
        unique.append(record)
    return unique


def _safe_model_inventory(models: list[Any]) -> list[dict[str, Any]]:
    inventory = []
    for item in models:
        model = _mapping(item)
        capabilities = _mapping(model.get("capabilities"))
        provider_config = _mapping(model.get("provider_configuration"))
        inventory.append(
            {
                "model_id": model.get("model_id"),
                "model_key": model.get("model_key") or model.get("code"),
                "code": model.get("code"),
                "name": model.get("name"),
                "provider": model.get("provider"),
                "provider_status": provider_config.get("status"),
                "provider_enabled": provider_config.get("enabled"),
                "model_type": model.get("model_type"),
                "deployment_mode": model.get("deployment_mode"),
                "status": model.get("status"),
                "enabled": model.get("enabled"),
                "default_for": model.get("default_for") or [],
                "capabilities": capabilities,
                "capability_count": len(capabilities),
                "readiness": model.get("readiness") or {},
                "diagnostics": model.get("diagnostics") or [],
                "configuration_present": bool(provider_config.get("configuration_present")),
                "secrets_configured": bool(provider_config.get("secrets_configured")),
                "secrets_exposed": False,
            }
        )
    return inventory


def _safe_provider_inventory(providers: list[Any]) -> list[dict[str, Any]]:
    inventory = []
    for item in providers:
        provider = _mapping(item)
        inventory.append(
            {
                "provider_id": provider.get("provider_id"),
                "provider_key": provider.get("provider_key"),
                "provider_type": provider.get("provider_type"),
                "adapter_type": provider.get("adapter_type"),
                "display_name": provider.get("display_name"),
                "status": provider.get("status"),
                "enabled": provider.get("enabled"),
                "configuration_present": provider.get("configuration_present"),
                "secrets_configured": provider.get("secrets_configured"),
                "health_state": provider.get("health_state"),
                "readiness": provider.get("readiness") or {},
                "provider_call_performed": False,
                "credentials_tested": False,
                "secrets_exposed": False,
            }
        )
    return inventory


def _model_capabilities(models: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter(str(model.get("model_type") or "unknown") for model in models)
    capability_counts: Counter[str] = Counter()
    for model in models:
        capabilities = _mapping(model.get("capabilities"))
        for key, value in capabilities.items():
            if bool(value):
                capability_counts[str(key)] += 1
    return {
        "model_count": len(models),
        "enabled_model_count": len([model for model in models if model.get("enabled")]),
        "models_by_type": dict(by_type),
        "capability_counts": dict(capability_counts),
        "capability_keys": sorted(capability_counts.keys()),
    }


def _default_model_profiles(models: list[dict[str, Any]]) -> dict[str, Any]:
    profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassigned = []
    for model in models:
        defaults = model.get("default_for") if isinstance(model.get("default_for"), list) else []
        if not defaults:
            unassigned.append(model.get("model_key"))
        for profile in defaults:
            profiles[str(profile)].append(
                {
                    "model_id": model.get("model_id"),
                    "model_key": model.get("model_key"),
                    "provider": model.get("provider"),
                    "status": model.get("status"),
                    "enabled": model.get("enabled"),
                }
            )
    return {
        "profile_count": len(profiles),
        "profiles": dict(profiles),
        "models_without_default_profile": [value for value in unassigned if value],
    }


def _assistant_model_usage(assistants: list[Any], models: list[dict[str, Any]]) -> dict[str, Any]:
    known_model_keys = {str(model.get("model_key")) for model in models if model.get("model_key")}
    usage = []
    referenced_models: Counter[str] = Counter()
    missing_references = []
    for assistant in _unique_by_persisted_identity(assistants, "assistant_id"):
        model_profile = _mapping(assistant.get("model_profile"))
        model_ref = (
            model_profile.get("model_key")
            or model_profile.get("model")
            or model_profile.get("model_name")
            or model_profile.get("default_model")
        )
        if model_ref:
            referenced_models[str(model_ref)] += 1
            if str(model_ref) not in known_model_keys:
                missing_references.append(
                    {
                        "assistant_id": assistant.get("assistant_id"),
                        "assistant_key": assistant.get("assistant_key"),
                        "model_reference": model_ref,
                    }
                )
        usage.append(
            {
                "assistant_id": assistant.get("assistant_id"),
                "assistant_key": assistant.get("assistant_key"),
                "assistant_name": assistant.get("assistant_name"),
                "assistant_status": assistant.get("assistant_status"),
                "assistant_type": assistant.get("assistant_type"),
                "organization_id": assistant.get("organization_id"),
                "ownership_scope": assistant.get("ownership_scope"),
                "data_origin": assistant.get("data_origin"),
                "model_profile": model_profile,
                "model_reference": model_ref,
                "prompt_profile": assistant.get("prompt_profile") or {},
                "guardrail_profile": assistant.get("guardrail_profile") or {},
                "readiness": assistant.get("readiness") or {},
            }
        )
    return {
        "assistant_count": len(usage),
        "assistants_with_model_profile": len([item for item in usage if item.get("model_profile")]),
        "referenced_models": dict(referenced_models),
        "missing_model_references": missing_references,
        "usage": usage,
    }


def _prompt_guardrail_relationships(
    prompts: list[Any],
    guardrails: list[Any],
    assistants: list[Any],
) -> dict[str, Any]:
    prompt_items = [_mapping(item) for item in prompts]
    guardrail_items = [_mapping(item) for item in guardrails]
    assistant_items = [_mapping(item) for item in assistants]
    return {
        "prompt_count": len(prompt_items),
        "guardrail_count": len(guardrail_items),
        "assistants_with_prompt_profile": len(
            [item for item in assistant_items if _mapping(item.get("prompt_profile"))]
        ),
        "assistants_with_guardrail_profile": len(
            [item for item in assistant_items if _mapping(item.get("guardrail_profile"))]
        ),
        "prompts": [
            {
                "prompt_id": prompt.get("prompt_id"),
                "prompt_key": prompt.get("prompt_key") or prompt.get("code"),
                "name": prompt.get("name"),
                "status": prompt.get("status"),
                "enabled": prompt.get("enabled"),
                "assigned_assistants_count": prompt.get("assigned_assistants_count"),
                "readiness": prompt.get("readiness") or {},
            }
            for prompt in prompt_items
        ],
        "guardrails": [
            {
                "guardrail_id": guardrail.get("guardrail_id"),
                "guardrail_key": guardrail.get("guardrail_key") or guardrail.get("code"),
                "name": guardrail.get("name"),
                "status": guardrail.get("status"),
                "enabled": guardrail.get("enabled"),
                "enforcement_mode": guardrail.get("enforcement_mode"),
                "assigned_assistants_count": guardrail.get("assigned_assistants_count"),
                "readiness": guardrail.get("readiness") or {},
            }
            for guardrail in guardrail_items
        ],
    }


def _gateway_readiness(
    runtime_executions: dict[str, Any],
    providers: list[dict[str, Any]],
    capability_availability: dict[str, Any],
) -> dict[str, Any]:
    gateway_executions = _as_int(runtime_executions.get("llm_gateway_executions"))
    enabled_providers = len([provider for provider in providers if provider.get("enabled")])
    generative = _mapping(capability_availability.get("generative_llm"))
    return {
        "gateway_ready": bool(generative.get("ready")),
        "gateway_execution_records": gateway_executions,
        "provider_configuration_ready": bool(generative.get("provider_configured")),
        "enabled_provider_count": enabled_providers,
        "execution_allowed_by_center": False,
        "provider_calls_performed": False,
        "credentials_tested": False,
        "llm_used": False,
        "warnings": []
        if enabled_providers
        else [
            {
                "code": "provider_not_enabled",
                "reason": "No enabled provider is configured. AI remains optional and disabled by default.",
            }
        ],
    }


def _execution_readiness(runtime_executions: dict[str, Any], policy_readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_assembly_executions": _as_int(runtime_executions.get("prompt_assembly_executions")),
        "llm_gateway_executions": _as_int(runtime_executions.get("llm_gateway_executions")),
        "llm_execution_records": _as_int(runtime_executions.get("llm_execution_records")),
        "citation_verification_executions": _as_int(runtime_executions.get("citation_verification_executions")),
        "assistant_response_executions": _as_int(runtime_executions.get("assistant_response_executions")),
        "assistant_sessions": _as_int(runtime_executions.get("assistant_sessions")),
        "assistant_runtime_executions": _as_int(runtime_executions.get("assistant_runtime_executions")),
        "llm_execution_by_status": runtime_executions.get("llm_execution_by_status") or {},
        "platform_works_without_ai": bool(policy_readiness.get("platform_works_without_ai")),
        "llm_execution_disabled_when_not_configured": bool(
            policy_readiness.get("llm_execution_disabled_when_not_configured")
        ),
        "execution_performed_by_center": False,
        "external_calls_performed": False,
    }


def _configuration_diagnostics(
    models: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    assistant_usage: dict[str, Any],
    ai_diagnostics: dict[str, Any],
    product_integration: dict[str, Any],
) -> dict[str, Any]:
    warnings = list(_listing(ai_diagnostics.get("warnings")))
    pending = list(_listing(ai_diagnostics.get("pending_capabilities")))
    degraded = list(_listing(ai_diagnostics.get("degraded_items")))
    if not models:
        degraded.append({"item_type": "domain", "item_id": "models", "status": "pending"})
    if not providers:
        degraded.append({"item_type": "domain", "item_id": "providers", "status": "pending"})
    for missing in assistant_usage.get("missing_model_references") or []:
        warnings.append({"code": "assistant_model_reference_missing", "details": missing})
    product_ai = _mapping(product_integration.get("ai_studio"))
    return {
        "blocking_issues": _listing(ai_diagnostics.get("blocking_issues")),
        "warnings": warnings,
        "pending_capabilities": pending,
        "degraded_items": degraded,
        "product_integration_ai": product_ai,
        "secrets_exposed": False,
    }


def _provider_diagnostics(providers: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(str(provider.get("status") or "unknown") for provider in providers)
    return {
        "secret_safe": True,
        "provider_count": len(providers),
        "enabled_provider_count": len([provider for provider in providers if provider.get("enabled")]),
        "configured_provider_count": len([provider for provider in providers if provider.get("configuration_present")]),
        "providers_with_secrets_configured": len(
            [provider for provider in providers if provider.get("secrets_configured")]
        ),
        "provider_status_counts": dict(by_status),
        "credentials_tested": False,
        "provider_calls_performed": False,
        "secrets_exposed": False,
        "providers": [
            {
                "provider_id": provider.get("provider_id"),
                "provider_key": provider.get("provider_key"),
                "status": provider.get("status"),
                "enabled": provider.get("enabled"),
                "configuration_present": provider.get("configuration_present"),
                "secrets_configured": provider.get("secrets_configured"),
                "health_state": provider.get("health_state"),
                "secrets_exposed": False,
            }
            for provider in providers
        ],
    }


def _optional_ai_status(
    policy_readiness: dict[str, Any],
    capability_availability: dict[str, Any],
) -> dict[str, Any]:
    generative = _mapping(capability_availability.get("generative_llm"))
    return {
        "ai_required": False,
        "ai_configured": bool(generative.get("ready")),
        "models_ready": bool(generative.get("model_configured")),
        "providers_ready": bool(generative.get("provider_configured")),
        "platform_works_without_ai": bool(policy_readiness.get("platform_works_without_ai")),
        "qdrant_required": False,
        "embeddings_required": False,
        "llm_used": False,
        "qdrant_used": False,
    }


def _recommendations(
    models: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    gateway: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations = []
    if not providers:
        recommendations.append(
            {"code": "configure_provider", "label": "Configure a provider when AI execution is required"}
        )
    if not models:
        recommendations.append({"code": "configure_model", "label": "Register governed models for assistants"})
    if not gateway.get("provider_configuration_ready"):
        recommendations.append(
            {"code": "review_provider_readiness", "label": "Review provider readiness before enabling AI"}
        )
    if diagnostics.get("warnings"):
        recommendations.append(
            {"code": "review_model_diagnostics", "label": "Review model and assistant configuration warnings"}
        )
    if not recommendations:
        recommendations.append(
            {"code": "monitor_model_governance", "label": "Monitor model, provider and gateway readiness"}
        )
    return recommendations


def build_model_provider_center_runtime(
    db: Session,
    *,
    organization_id: UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    ai_studio = build_ai_studio_runtime(
        db,
        organization_id=organization_id,
        platform_scope=platform_scope,
    )
    product_integration = build_product_integration_runtime(db) if platform_scope else {}
    models_and_providers = _mapping(ai_studio.get("models_and_providers"))
    model_inventory = _safe_model_inventory(_listing(models_and_providers.get("models")))
    provider_inventory = _safe_provider_inventory(_listing(models_and_providers.get("providers")))
    runtime_executions = _mapping(ai_studio.get("runtime_executions"))
    capability_availability = _mapping(ai_studio.get("capability_availability"))
    policy_readiness = _mapping(ai_studio.get("policy_readiness"))
    assistant_usage = _assistant_model_usage(_listing(ai_studio.get("assistants")), model_inventory)
    gateway = _gateway_readiness(runtime_executions, provider_inventory, capability_availability)
    execution = _execution_readiness(runtime_executions, policy_readiness)
    diagnostics = _configuration_diagnostics(
        model_inventory,
        provider_inventory,
        assistant_usage,
        _mapping(ai_studio.get("diagnostics")),
        product_integration,
    )
    provider_diagnostics = _provider_diagnostics(provider_inventory)
    optional_ai = _optional_ai_status(policy_readiness, capability_availability)
    pending_capabilities = list(diagnostics.get("pending_capabilities") or [])
    warnings = list(diagnostics.get("warnings") or [])
    warnings.extend(gateway.get("warnings") or [])
    recommendations = _recommendations(model_inventory, provider_inventory, gateway, diagnostics)
    runtime_status = (
        "ready" if model_inventory or provider_inventory or optional_ai["platform_works_without_ai"] else "degraded"
    )

    return {
        "model_provider_center_runtime_schema_version": MODEL_PROVIDER_CENTER_RUNTIME_SCHEMA_VERSION,
        "runtime_name": MODEL_PROVIDER_CENTER_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "model_provider_center_ready": runtime_status == "ready",
            "model_count": len(model_inventory),
            "provider_count": len(provider_inventory),
            "enabled_model_count": len([model for model in model_inventory if model.get("enabled")]),
            "enabled_provider_count": len([provider for provider in provider_inventory if provider.get("enabled")]),
            "gateway_ready": gateway.get("gateway_ready"),
            "ai_required": False,
            "optional_ai_ready": optional_ai.get("platform_works_without_ai"),
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
            "secrets_exposed": False,
        },
        "model_inventory": model_inventory,
        "provider_inventory": provider_inventory,
        "gateway_readiness": gateway,
        "model_capabilities": _model_capabilities(model_inventory),
        "default_model_profiles": _default_model_profiles(model_inventory),
        "assistant_model_usage": assistant_usage,
        "prompt_guardrail_relationships": _prompt_guardrail_relationships(
            _listing(ai_studio.get("prompts")),
            _listing(ai_studio.get("guardrails")),
            _listing(ai_studio.get("assistants")),
        ),
        "execution_readiness": execution,
        "capability_availability": capability_availability,
        "historical_usage": _mapping(capability_availability.get("historical_usage")),
        "configuration_diagnostics": diagnostics,
        "provider_diagnostics": provider_diagnostics,
        "optional_ai_status": optional_ai,
        "pending_capabilities": pending_capabilities,
        "warnings": warnings,
        "recommendations": recommendations,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
        "secrets_exposed": False,
    }
