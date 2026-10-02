import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import Guardrail, Model, Prompt, Provider, RuntimeProfile

CONTEXT_ONLY = "context_only"
EXTRACTIVE = "extractive"
ASSISTED = "assisted"

SUPPORTED_ANSWER_MODES = {CONTEXT_ONLY, EXTRACTIVE, ASSISTED}


@dataclass(frozen=True)
class RuntimeResolution:
    requested_answer_mode: str
    resolved_answer_mode: str
    runtime_profile_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    prompt_id: uuid.UUID | None = None
    guardrail_id: uuid.UUID | None = None
    generation_requested: bool = False
    generation_allowed: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    provider_configured: bool = False
    model_configured: bool = False
    prompt_configured: bool = False
    guardrail_configured: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeResolverService:
    """Resolve AI runtime registry state without executing AI providers."""

    def resolve(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        requested_answer_mode: str,
    ) -> RuntimeResolution:
        answer_mode = self._normalize_answer_mode(requested_answer_mode)

        if answer_mode not in SUPPORTED_ANSWER_MODES:
            return RuntimeResolution(
                requested_answer_mode=requested_answer_mode,
                resolved_answer_mode=EXTRACTIVE,
                generation_requested=False,
                generation_allowed=False,
                fallback_used=True,
                fallback_reason="unsupported_answer_mode",
                metadata={"resolver": "runtime_resolver_v1"},
            )

        if answer_mode == CONTEXT_ONLY:
            return RuntimeResolution(
                requested_answer_mode=requested_answer_mode,
                resolved_answer_mode=CONTEXT_ONLY,
                generation_requested=False,
                generation_allowed=False,
                fallback_used=False,
                metadata={"resolver": "runtime_resolver_v1"},
            )

        if answer_mode == EXTRACTIVE:
            return RuntimeResolution(
                requested_answer_mode=requested_answer_mode,
                resolved_answer_mode=EXTRACTIVE,
                generation_requested=False,
                generation_allowed=False,
                fallback_used=False,
                metadata={"resolver": "runtime_resolver_v1"},
            )

        profile = self._find_runtime_profile(db, organization_id=organization_id, answer_mode=ASSISTED)
        if profile is None:
            return self._fallback(requested_answer_mode=requested_answer_mode, reason="runtime_profile_not_configured")

        if not profile.generation_enabled:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="generation_not_enabled",
                profile=profile,
            )

        provider = db.get(Provider, profile.provider_id) if profile.provider_id else None
        if provider is None:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="provider_not_configured",
                profile=profile,
            )
        if not provider.enabled:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="provider_disabled",
                profile=profile,
                provider=provider,
            )
        if provider.status != "active":
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="provider_disabled",
                profile=profile,
                provider=provider,
            )
        if provider.health_state not in {"healthy", "unknown"}:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="provider_unhealthy",
                profile=profile,
                provider=provider,
            )

        model = db.get(Model, profile.model_id) if profile.model_id else None
        if model is None:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="model_not_configured",
                profile=profile,
                provider=provider,
            )
        if not model.enabled or model.status not in {"active", "available"}:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="model_disabled",
                profile=profile,
                provider=provider,
                model=model,
            )

        prompt = db.get(Prompt, profile.prompt_id) if profile.prompt_id else None
        if prompt is None:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="prompt_not_configured",
                profile=profile,
                provider=provider,
                model=model,
            )
        if not prompt.enabled or prompt.status != "active":
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="prompt_unresolved",
                profile=profile,
                provider=provider,
                model=model,
                prompt=prompt,
            )

        guardrail = db.get(Guardrail, profile.guardrail_id) if profile.guardrail_id else None
        if profile.guardrail_id and guardrail is None:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="guardrail_not_configured",
                profile=profile,
                provider=provider,
                model=model,
                prompt=prompt,
            )
        if guardrail is not None and not guardrail.enabled:
            return self._fallback(
                requested_answer_mode=requested_answer_mode,
                reason="guardrail_blocked",
                profile=profile,
                provider=provider,
                model=model,
                prompt=prompt,
                guardrail=guardrail,
            )

        return RuntimeResolution(
            requested_answer_mode=requested_answer_mode,
            resolved_answer_mode=ASSISTED,
            runtime_profile_id=profile.id,
            provider_id=provider.id,
            model_id=model.id,
            prompt_id=prompt.id,
            guardrail_id=guardrail.id if guardrail else None,
            generation_requested=True,
            generation_allowed=True,
            fallback_used=False,
            fallback_reason=None,
            provider_configured=True,
            model_configured=True,
            prompt_configured=True,
            guardrail_configured=guardrail is not None,
            metadata={
                "resolver": "runtime_resolver_v1",
                "provider_adapter": provider.adapter_type,
                "provider_type": provider.provider_type,
                "model_type": model.model_type,
                "prompt_type": prompt.prompt_type,
                "guardrail_type": guardrail.guardrail_type if guardrail else None,
            },
        )

    def _normalize_answer_mode(self, requested_answer_mode: str) -> str:
        return requested_answer_mode.strip().lower().replace("-", "_")

    def _find_runtime_profile(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        answer_mode: str,
    ) -> RuntimeProfile | None:
        candidates: list[tuple[uuid.UUID | None, bool]] = []
        if organization_id is not None:
            candidates.append((organization_id, True))
        candidates.append((None, True))
        if organization_id is not None:
            candidates.append((organization_id, False))
        candidates.append((None, False))

        for candidate_org_id, is_default in candidates:
            statement = (
                select(RuntimeProfile)
                .where(
                    RuntimeProfile.organization_id.is_(None)
                    if candidate_org_id is None
                    else RuntimeProfile.organization_id == candidate_org_id
                )
                .where(RuntimeProfile.answer_mode == answer_mode)
                .where(RuntimeProfile.status == "active")
                .where(RuntimeProfile.is_default.is_(is_default))
                .limit(1)
            )
            profile = db.scalars(statement).first()
            if profile is not None:
                return profile
        return None

    def _fallback(
        self,
        *,
        requested_answer_mode: str,
        reason: str,
        profile: RuntimeProfile | None = None,
        provider: Provider | None = None,
        model: Model | None = None,
        prompt: Prompt | None = None,
        guardrail: Guardrail | None = None,
    ) -> RuntimeResolution:
        return RuntimeResolution(
            requested_answer_mode=requested_answer_mode,
            resolved_answer_mode=EXTRACTIVE,
            runtime_profile_id=profile.id if profile else None,
            provider_id=provider.id if provider else None,
            model_id=model.id if model else None,
            prompt_id=prompt.id if prompt else None,
            guardrail_id=guardrail.id if guardrail else None,
            generation_requested=True,
            generation_allowed=False,
            fallback_used=True,
            fallback_reason=reason,
            provider_configured=provider is not None,
            model_configured=model is not None,
            prompt_configured=prompt is not None,
            guardrail_configured=guardrail is not None,
            metadata={"resolver": "runtime_resolver_v1"},
        )
