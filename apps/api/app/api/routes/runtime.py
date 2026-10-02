from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.runtime_execution import (
    RuntimeExecuteRequest,
    RuntimeExecuteResponse,
    RuntimeResolveRequest,
    RuntimeResolveResponse,
    RuntimeStatusResponse,
)
from app.services.runtime_resolver import RuntimeResolverService

router = APIRouter(prefix="/ai/runtime", tags=["ai-runtime"])


@router.get("/status", response_model=RuntimeStatusResponse)
def runtime_status() -> RuntimeStatusResponse:
    return RuntimeStatusResponse()


@router.post("/resolve", response_model=RuntimeResolveResponse)
def resolve_runtime(
    payload: RuntimeResolveRequest,
    db: Session = Depends(get_db),
) -> RuntimeResolveResponse:
    result = RuntimeResolverService().resolve(
        db,
        organization_id=payload.organization_id,
        requested_answer_mode=payload.requested_answer_mode,
    )
    return RuntimeResolveResponse(
        requested_answer_mode=result.requested_answer_mode,
        resolved_answer_mode=result.resolved_answer_mode,
        runtime_profile_id=result.runtime_profile_id,
        provider_id=result.provider_id,
        model_id=result.model_id,
        prompt_id=result.prompt_id,
        guardrail_id=result.guardrail_id,
        generation_requested=result.generation_requested,
        generation_allowed=result.generation_allowed,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        provider_configured=result.provider_configured,
        model_configured=result.model_configured,
        prompt_configured=result.prompt_configured,
        guardrail_configured=result.guardrail_configured,
        execution_attempted=False,
        provider_execution_performed=False,
        generation_performed=False,
        metadata=dict(result.metadata),
    )


@router.post("/execute", response_model=RuntimeExecuteResponse)
def execute_runtime(payload: RuntimeExecuteRequest) -> RuntimeExecuteResponse:
    requested = payload.requested_answer_mode.strip().lower().replace("-", "_")
    resolved = requested if requested in {"context_only", "extractive"} else "extractive"
    fallback_reason = "execution_not_enabled" if requested == "assisted" else None
    return RuntimeExecuteResponse(
        status="fallback" if fallback_reason else "not_attempted",
        requested_answer_mode=payload.requested_answer_mode,
        resolved_answer_mode=resolved,
        answer_text=None,
        answer_generated=False,
        execution_attempted=False,
        fallback_used=fallback_reason is not None,
        fallback_reason=fallback_reason,
        error_code=fallback_reason,
        context_preserved=True,
        citation_count=len(payload.citations),
        provider_execution_performed=False,
        secret_resolution_performed=False,
        generation_performed=False,
        metadata={
            "contract_version": "runtime_execution_api_v1",
            "context_item_count": len(payload.context),
            "execution_enabled": False,
        },
    )
