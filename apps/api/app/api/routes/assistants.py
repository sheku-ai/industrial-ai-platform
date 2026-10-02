from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantContextPackage,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantResponse,
    AssistantRetrievalExecutionPlan,
    AssistantRetrievalPlan,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
)
from app.repositories.assistant import AssistantRepository
from app.schemas.assistants import (
    AssistantChatHealthResponse,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantCitationVerificationCreateRequest,
    AssistantCitationVerificationHealthResponse,
    AssistantCitationVerificationResponse,
    AssistantContextBuilderCreateRequest,
    AssistantContextBuilderHealthResponse,
    AssistantContextPackageResponse,
    AssistantCreateRequest,
    AssistantCreateResponse,
    AssistantHealthResponse,
    AssistantLlmExecutionCreateRequest,
    AssistantLlmExecutionHealthResponse,
    AssistantLlmExecutionResponse,
    AssistantLlmGatewayCreateRequest,
    AssistantLlmGatewayHealthResponse,
    AssistantLlmGatewayResponse,
    AssistantPromptAssemblyCreateRequest,
    AssistantPromptAssemblyHealthResponse,
    AssistantPromptPackageResponse,
    AssistantResponseCreateRequest,
    AssistantResponseHealthResponse,
    AssistantResponseResponse,
    AssistantRetrievalExecutionReadinessCreateRequest,
    AssistantRetrievalExecutionReadinessHealthResponse,
    AssistantRetrievalExecutionReadinessResponse,
    AssistantRetrievalPlanCreateRequest,
    AssistantRetrievalPlanHealthResponse,
    AssistantRetrievalPlanResponse,
    AssistantRunCreateRequest,
    AssistantRunResponse,
    AssistantSearchExecutionCreateRequest,
    AssistantSearchExecutionHealthResponse,
    AssistantSearchExecutionResponse,
    AssistantSessionCreateRequest,
    AssistantSessionResponse,
    ConversationCreateRequest,
    ConversationHealthResponse,
    ConversationResponse,
    ConversationTurnCreateRequest,
    ConversationTurnResponse,
)
from app.services.assistant_citation_verification_runtime import (
    build_assistant_citation_verification_health,
    build_assistant_citation_verification_runtime,
    read_assistant_citation_verification,
)
from app.services.assistant_context_builder_runtime import (
    build_assistant_context_builder_health,
    build_assistant_context_builder_runtime,
    read_assistant_context_package,
)
from app.services.assistant_llm_execution_runtime import (
    build_assistant_llm_execution_health,
    build_assistant_llm_execution_runtime,
    read_assistant_llm_execution,
)
from app.services.assistant_llm_gateway_runtime import (
    build_assistant_llm_gateway_health,
    build_assistant_llm_gateway_runtime,
    read_assistant_llm_gateway,
)
from app.services.assistant_prompt_assembly_runtime import (
    build_assistant_prompt_assembly_health,
    build_assistant_prompt_assembly_runtime,
    read_assistant_prompt_package,
)
from app.services.assistant_response_runtime import (
    build_assistant_response_health,
    build_assistant_response_runtime,
    read_assistant_response,
)
from app.services.assistant_retrieval_execution_runtime import (
    build_assistant_retrieval_execution_health,
    build_assistant_retrieval_execution_readiness_runtime,
    read_assistant_retrieval_execution_plan,
)
from app.services.assistant_retrieval_runtime import (
    build_assistant_retrieval_health,
    build_assistant_retrieval_runtime,
    read_assistant_retrieval_plan,
)
from app.services.assistant_runtime import (
    build_assistant_health,
    build_assistant_run_runtime,
    build_assistant_runtime,
    build_assistant_session_runtime,
    list_assistants_runtime,
    read_assistant,
    read_assistant_run,
    read_assistant_session,
)
from app.services.assistant_search_execution_runtime import (
    build_assistant_search_execution_health,
    build_assistant_search_execution_runtime,
    read_assistant_search_execution,
)
from app.services.chat_runtime import build_chat_health, build_chat_runtime, list_chat_runtime, read_chat_runtime
from app.services.conversation_gateway import build_conversation_health
from app.services.conversation_runtime import (
    attach_assistant_response_to_conversation_runtime,
    build_conversation_runtime,
    build_conversation_turn_runtime,
    list_conversation_turns_runtime,
    list_conversations_runtime,
    read_conversation,
)

router = APIRouter(prefix="/assistants", tags=["assistants"])


def _require(context: RuntimeRequestContext, action: str) -> None:
    if not context.has_permission("platform.assistants", action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"assistant {action} permission is required",
        )


def _organization_id(context: RuntimeRequestContext) -> UUID:
    if context.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization scope is required for conversations",
        )
    return context.organization_id


def _validation_generated(metadata: dict) -> bool:
    return bool(
        metadata.get("validation_generated") is True
        or metadata.get("scenario") == "local_product_acceptance"
        or metadata.get("execution_key")
        or metadata.get("smoke_runtime")
    )


def _authorize_artifact(
    db: Session,
    context: RuntimeRequestContext,
    model: object,
    identifier_column: object,
    identifier: str,
    resource_name: str,
) -> None:
    _require(context, "read")
    try:
        artifact_id = UUID(identifier)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} not found") from exc
    artifact = AssistantRepository(db).get_scoped_artifact(
        model,
        identifier_column,
        artifact_id,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} not found")


_TECHNICAL_SECRET_FIELDS = {
    "system_prompt",
    "assistant_instructions",
    "assembled_context",
    "citation_section",
    "request_payload_metadata",
    "raw_output_text",
    "raw_output_metadata",
    "cost_metadata",
}


def _redact_technical_payload(value):
    if isinstance(value, dict):
        return {
            key: _redact_technical_payload(item) for key, item in value.items() if key not in _TECHNICAL_SECRET_FIELDS
        }
    if isinstance(value, list):
        return [_redact_technical_payload(item) for item in value]
    return value


@router.post("", response_model=AssistantCreateResponse)
def create_assistant(
    payload: AssistantCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    validation_generated = _validation_generated(payload.runtime_metadata)
    data_origin = "validation" if validation_generated else "operational"
    return build_assistant_runtime(
        db,
        organization_id=context.organization_id,
        ownership_scope="global" if context.scope_type == "platform" else "organization",
        data_origin=data_origin,
        assistant_name=payload.assistant_name,
        assistant_key=payload.assistant_key,
        assistant_version=payload.assistant_version,
        assistant_type=payload.assistant_type,
        description=payload.description,
        default_search_mode=payload.default_search_mode,
        allowed_runtime_domains=payload.allowed_runtime_domains,
        guardrail_profile=payload.guardrail_profile,
        requested_by=payload.requested_by,
        conversation_reference=payload.conversation_reference,
        requested_query=payload.requested_query,
        runtime_context=payload.runtime_context,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("")
def list_assistants(
    assistant_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    return list_assistants_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
        assistant_status=assistant_status,
        limit=limit,
    )


@router.get("/health", response_model=AssistantHealthResponse)
def get_assistant_health(db: Session = Depends(get_db)):
    return build_assistant_health(db)


@router.get("/sessions/{assistant_session_id}", response_model=AssistantSessionResponse)
def get_assistant_session(
    assistant_session_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db, context, AssistantSession, AssistantSession.assistant_session_id, assistant_session_id, "assistant session"
    )
    result = read_assistant_session(db, assistant_session_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant session not found")
    return result


@router.get("/runs/{assistant_run_id}", response_model=AssistantRunResponse)
def get_assistant_run(
    assistant_run_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db, context, AssistantRuntimeRun, AssistantRuntimeRun.assistant_run_id, assistant_run_id, "assistant run"
    )
    result = read_assistant_run(db, assistant_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant run not found")
    return result


@router.get("/retrieval-plans/health", response_model=AssistantRetrievalPlanHealthResponse)
def get_assistant_retrieval_plan_health(db: Session = Depends(get_db)):
    return build_assistant_retrieval_health(db)


@router.get("/retrieval-executions/health", response_model=AssistantRetrievalExecutionReadinessHealthResponse)
def get_assistant_retrieval_execution_health(db: Session = Depends(get_db)):
    return build_assistant_retrieval_execution_health(db)


@router.get("/search-executions/health", response_model=AssistantSearchExecutionHealthResponse)
def get_assistant_search_execution_health(db: Session = Depends(get_db)):
    return build_assistant_search_execution_health(db)


@router.get("/context-packages/health", response_model=AssistantContextBuilderHealthResponse)
def get_assistant_context_builder_health(db: Session = Depends(get_db)):
    return build_assistant_context_builder_health(db)


@router.get("/prompt-packages/health", response_model=AssistantPromptAssemblyHealthResponse)
def get_assistant_prompt_assembly_health(db: Session = Depends(get_db)):
    return build_assistant_prompt_assembly_health(db)


@router.get("/llm-gateways/health", response_model=AssistantLlmGatewayHealthResponse)
def get_assistant_llm_gateway_health(db: Session = Depends(get_db)):
    return build_assistant_llm_gateway_health(db)


@router.get("/llm-executions/health", response_model=AssistantLlmExecutionHealthResponse)
def get_assistant_llm_execution_health(db: Session = Depends(get_db)):
    return build_assistant_llm_execution_health(db)


@router.get("/citation-verifications/health", response_model=AssistantCitationVerificationHealthResponse)
def get_assistant_citation_verification_health(db: Session = Depends(get_db)):
    return build_assistant_citation_verification_health(db)


@router.get("/responses/health", response_model=AssistantResponseHealthResponse)
def get_assistant_response_health(db: Session = Depends(get_db)):
    return build_assistant_response_health(db)


@router.get("/conversations/health", response_model=ConversationHealthResponse)
def get_conversation_health(db: Session = Depends(get_db)):
    return build_conversation_health(db)


@router.get("/chat/health", response_model=AssistantChatHealthResponse)
def get_chat_health(db: Session = Depends(get_db)):
    return build_chat_health(db)


@router.get("/chat", response_model=AssistantChatResponse)
def list_chat_conversations(
    assistant_id: str | None = None,
    conversation_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    return list_chat_runtime(
        db,
        organization_id=_organization_id(context),
        assistant_id=assistant_id,
        conversation_status=conversation_status,
        limit=limit,
    )


@router.post("/chat", response_model=AssistantChatResponse)
def create_chat_turn(
    payload: AssistantChatRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    result = build_chat_runtime(
        db,
        organization_id=_organization_id(context),
        data_origin="validation" if _validation_generated(payload.runtime_metadata) else "operational",
        assistant_id=payload.assistant_id,
        conversation_id=payload.conversation_id,
        message=payload.message,
        requested_by=context.actor_reference or payload.requested_by,
        runtime_context={**payload.runtime_context, "correlation_id": context.correlation_id},
        runtime_metadata={
            **payload.runtime_metadata,
            "correlation_id": context.correlation_id,
            **({"idempotency_key": payload.request_id} if payload.request_id else {}),
        },
    )
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/chat/{conversation_id}", response_model=AssistantChatResponse)
def get_chat_conversation(
    conversation_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    result = read_chat_runtime(db, conversation_id, organization_id=_organization_id(context))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return result


@router.get("/conversations", response_model=ConversationResponse)
def list_conversations(
    assistant_id: str | None = None,
    conversation_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    return list_conversations_runtime(
        db,
        organization_id=_organization_id(context),
        assistant_id=assistant_id,
        conversation_status=conversation_status,
        limit=limit,
    )


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    payload: ConversationCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    result = build_conversation_runtime(
        db,
        organization_id=_organization_id(context),
        data_origin=("validation" if _validation_generated(payload.conversation_metadata) else "operational"),
        assistant_id=payload.assistant_id,
        assistant_session_id=payload.assistant_session_id,
        conversation_title=payload.conversation_title,
        conversation_reference=payload.conversation_reference,
        requested_by=payload.requested_by,
        runtime_context=payload.runtime_context,
        conversation_metadata=payload.conversation_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant or assistant session not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    result = read_conversation(db, conversation_id, organization_id=_organization_id(context))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return result


@router.get("/conversations/{conversation_id}/turns", response_model=ConversationTurnResponse)
def list_conversation_turns(
    conversation_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    result = list_conversation_turns_runtime(
        db, conversation_id=conversation_id, organization_id=_organization_id(context), limit=limit
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return result


@router.post("/conversations/{conversation_id}/turns", response_model=ConversationTurnResponse)
def create_conversation_turn(
    conversation_id: str,
    payload: ConversationTurnCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    result = build_conversation_turn_runtime(
        db,
        organization_id=_organization_id(context),
        conversation_id=conversation_id,
        turn_role=payload.turn_role,
        input_text=payload.input_text,
        output_text=payload.output_text,
        assistant_run_id=payload.assistant_run_id,
        response_format=payload.response_format,
        citation_summary=payload.citation_summary,
        ordered_citations=payload.ordered_citations,
        turn_metadata=payload.turn_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.post(
    "/conversations/{conversation_id}/assistant-responses/{assistant_response_id}",
    response_model=ConversationTurnResponse,
)
def attach_assistant_response_to_conversation(
    conversation_id: str,
    assistant_response_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantResponse,
        AssistantResponse.assistant_response_id,
        assistant_response_id,
        "assistant response",
    )
    result = attach_assistant_response_to_conversation_runtime(
        db,
        organization_id=_organization_id(context),
        conversation_id=conversation_id,
        assistant_response_id=assistant_response_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation or assistant response not found"
        )
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/responses/{assistant_response_id}", response_model=AssistantResponseResponse)
def get_assistant_response(
    assistant_response_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantResponse,
        AssistantResponse.assistant_response_id,
        assistant_response_id,
        "assistant response",
    )
    result = read_assistant_response(
        db,
        assistant_response_id,
        organization_id=str(context.organization_id) if context.organization_id else None,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant response not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result)
    return result


@router.post("/citation-verifications/{citation_verification_id}/response", response_model=AssistantResponseResponse)
def create_assistant_response(
    citation_verification_id: str,
    payload: AssistantResponseCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantCitationVerification,
        AssistantCitationVerification.citation_verification_id,
        citation_verification_id,
        "assistant citation verification",
    )
    result = build_assistant_response_runtime(
        db,
        citation_verification_id=citation_verification_id,
        organization_id=context.organization_id,
        response_metadata=payload.response_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant citation verification not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/citation-verifications/{citation_verification_id}", response_model=AssistantCitationVerificationResponse)
def get_assistant_citation_verification(
    citation_verification_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantCitationVerification,
        AssistantCitationVerification.citation_verification_id,
        citation_verification_id,
        "assistant citation verification",
    )
    result = read_assistant_citation_verification(db, citation_verification_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant citation verification not found")
    return result


@router.post(
    "/llm-executions/{llm_execution_id}/citation-verification", response_model=AssistantCitationVerificationResponse
)
def create_assistant_citation_verification(
    llm_execution_id: str,
    payload: AssistantCitationVerificationCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantLlmExecution,
        AssistantLlmExecution.llm_execution_id,
        llm_execution_id,
        "assistant llm execution",
    )
    result = build_assistant_citation_verification_runtime(
        db,
        llm_execution_id=llm_execution_id,
        organization_id=context.organization_id,
        request_metadata=payload.request_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant llm execution not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/llm-executions/{llm_execution_id}", response_model=AssistantLlmExecutionResponse)
def get_assistant_llm_execution(
    llm_execution_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantLlmExecution,
        AssistantLlmExecution.llm_execution_id,
        llm_execution_id,
        "assistant llm execution",
    )
    result = read_assistant_llm_execution(db, llm_execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant llm execution not found")
    return _redact_technical_payload(result)


@router.post("/llm-gateways/{gateway_id}/execute", response_model=AssistantLlmExecutionResponse)
def create_assistant_llm_execution(
    gateway_id: str,
    payload: AssistantLlmExecutionCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantLlmInvocationPlan,
        AssistantLlmInvocationPlan.gateway_id,
        gateway_id,
        "assistant llm gateway",
    )
    result = build_assistant_llm_execution_runtime(
        db,
        gateway_id=gateway_id,
        organization_id=context.organization_id,
        request_payload_metadata=payload.request_payload_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant llm gateway not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return _redact_technical_payload(result)


@router.get("/llm-gateways/{gateway_id}", response_model=AssistantLlmGatewayResponse)
def get_assistant_llm_gateway(
    gateway_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantLlmInvocationPlan,
        AssistantLlmInvocationPlan.gateway_id,
        gateway_id,
        "assistant llm gateway",
    )
    result = read_assistant_llm_gateway(db, gateway_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant llm gateway not found")
    return _redact_technical_payload(result)


@router.post("/prompt-packages/{prompt_package_id}/llm-gateway", response_model=AssistantLlmGatewayResponse)
def create_assistant_llm_gateway(
    prompt_package_id: str,
    payload: AssistantLlmGatewayCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantPromptPackage,
        AssistantPromptPackage.prompt_package_id,
        prompt_package_id,
        "assistant prompt package",
    )
    result = build_assistant_llm_gateway_runtime(
        db,
        prompt_package_id=prompt_package_id,
        organization_id=context.organization_id,
        provider_type=payload.provider_type,
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        planned_temperature=payload.planned_temperature,
        planned_max_tokens=payload.planned_max_tokens,
        planned_top_p=payload.planned_top_p,
        planned_stop_sequences=payload.planned_stop_sequences,
        planned_seed=payload.planned_seed,
        planned_timeout=payload.planned_timeout,
        gateway_metadata=payload.gateway_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant prompt package not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return _redact_technical_payload(result)


@router.get("/prompt-packages/{prompt_package_id}", response_model=AssistantPromptPackageResponse)
def get_assistant_prompt_package(
    prompt_package_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantPromptPackage,
        AssistantPromptPackage.prompt_package_id,
        prompt_package_id,
        "assistant prompt package",
    )
    result = read_assistant_prompt_package(db, prompt_package_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant prompt package not found")
    return _redact_technical_payload(result)


@router.post("/context-packages/{context_package_id}/prompt", response_model=AssistantPromptPackageResponse)
def create_assistant_prompt_package(
    context_package_id: str,
    payload: AssistantPromptAssemblyCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantContextPackage,
        AssistantContextPackage.context_package_id,
        context_package_id,
        "assistant context package",
    )
    result = build_assistant_prompt_assembly_runtime(
        db,
        context_package_id=context_package_id,
        organization_id=context.organization_id,
        prompt_metadata=payload.prompt_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant context package not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return _redact_technical_payload(result)


@router.get("/context-packages/{context_package_id}", response_model=AssistantContextPackageResponse)
def get_assistant_context_package(
    context_package_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantContextPackage,
        AssistantContextPackage.context_package_id,
        context_package_id,
        "assistant context package",
    )
    result = read_assistant_context_package(db, context_package_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant context package not found")
    return result


@router.post("/search-executions/{search_execution_id}/context", response_model=AssistantContextPackageResponse)
def create_assistant_context_package(
    search_execution_id: str,
    payload: AssistantContextBuilderCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantSearchExecution,
        AssistantSearchExecution.search_execution_id,
        search_execution_id,
        "assistant search execution",
    )
    result = build_assistant_context_builder_runtime(
        db,
        search_execution_id=search_execution_id,
        organization_id=context.organization_id,
        package_metadata=payload.package_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant search execution not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/search-executions/{search_execution_id}", response_model=AssistantSearchExecutionResponse)
def get_assistant_search_execution(
    search_execution_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantSearchExecution,
        AssistantSearchExecution.search_execution_id,
        search_execution_id,
        "assistant search execution",
    )
    result = read_assistant_search_execution(db, search_execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant search execution not found")
    return result


@router.get("/retrieval-executions/{execution_plan_id}", response_model=AssistantRetrievalExecutionReadinessResponse)
def get_assistant_retrieval_execution(
    execution_plan_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantRetrievalExecutionPlan,
        AssistantRetrievalExecutionPlan.execution_plan_id,
        execution_plan_id,
        "assistant retrieval execution readiness",
    )
    result = read_assistant_retrieval_execution_plan(db, execution_plan_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assistant retrieval execution readiness not found"
        )
    return result


@router.post("/retrieval-executions/{execution_plan_id}/search", response_model=AssistantSearchExecutionResponse)
def create_assistant_search_execution(
    execution_plan_id: str,
    payload: AssistantSearchExecutionCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantRetrievalExecutionPlan,
        AssistantRetrievalExecutionPlan.execution_plan_id,
        execution_plan_id,
        "assistant retrieval execution readiness",
    )
    result = build_assistant_search_execution_runtime(
        db,
        execution_plan_id=execution_plan_id,
        organization_id=context.organization_id,
        top_k=payload.top_k,
        search_config=payload.search_config,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="assistant retrieval execution readiness not found"
        )
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.post(
    "/retrieval-plans/{retrieval_plan_id}/execution-readiness",
    response_model=AssistantRetrievalExecutionReadinessResponse,
)
def create_assistant_retrieval_execution_readiness(
    retrieval_plan_id: str,
    payload: AssistantRetrievalExecutionReadinessCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    _authorize_artifact(
        db,
        context,
        AssistantRetrievalPlan,
        AssistantRetrievalPlan.retrieval_plan_id,
        retrieval_plan_id,
        "assistant retrieval plan",
    )
    result = build_assistant_retrieval_execution_readiness_runtime(
        db,
        retrieval_plan_id=retrieval_plan_id,
        organization_id=context.organization_id,
        readiness_metadata=payload.readiness_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant retrieval plan not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.get("/retrieval-plans/{retrieval_plan_id}", response_model=AssistantRetrievalPlanResponse)
def get_assistant_retrieval_plan(
    retrieval_plan_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _authorize_artifact(
        db,
        context,
        AssistantRetrievalPlan,
        AssistantRetrievalPlan.retrieval_plan_id,
        retrieval_plan_id,
        "assistant retrieval plan",
    )
    result = read_assistant_retrieval_plan(db, retrieval_plan_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant retrieval plan not found")
    return result


@router.get("/{assistant_id}", response_model=AssistantCreateResponse)
def get_assistant(
    assistant_id: str,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "read")
    result = read_assistant(
        db,
        assistant_id,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant not found")
    return result


@router.post("/{assistant_id}/sessions", response_model=AssistantSessionResponse)
def create_assistant_session(
    assistant_id: str,
    payload: AssistantSessionCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    if read_assistant(db, assistant_id, organization_id=context.organization_id, platform_scope=False) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant not found")
    result = build_assistant_session_runtime(
        db,
        assistant_id=assistant_id,
        organization_id=context.organization_id,
        requested_by=payload.requested_by,
        conversation_reference=payload.conversation_reference,
        runtime_context=payload.runtime_context,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant not found")
    return result


@router.post("/{assistant_id}/runs", response_model=AssistantRunResponse)
def create_assistant_run(
    assistant_id: str,
    payload: AssistantRunCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    if read_assistant(db, assistant_id, organization_id=context.organization_id, platform_scope=False) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant not found")
    _authorize_artifact(
        db,
        context,
        AssistantSession,
        AssistantSession.assistant_session_id,
        payload.assistant_session_id,
        "assistant session",
    )
    result = build_assistant_run_runtime(
        db,
        assistant_id=assistant_id,
        assistant_session_id=payload.assistant_session_id,
        organization_id=context.organization_id,
        requested_query=payload.requested_query,
        selected_search_mode=payload.selected_search_mode,
        selected_runtime_domain=payload.selected_runtime_domain,
        runtime_metadata=payload.runtime_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant or assistant session not found")
    return result


@router.post("/{assistant_id}/retrieval-plan", response_model=AssistantRetrievalPlanResponse)
def create_assistant_retrieval_plan(
    assistant_id: str,
    payload: AssistantRetrievalPlanCreateRequest,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    _require(context, "administer")
    if read_assistant(db, assistant_id, organization_id=context.organization_id, platform_scope=False) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant not found")
    if payload.assistant_session_id:
        _authorize_artifact(
            db,
            context,
            AssistantSession,
            AssistantSession.assistant_session_id,
            payload.assistant_session_id,
            "assistant session",
        )
    result = build_assistant_retrieval_runtime(
        db,
        assistant_id=assistant_id,
        assistant_session_id=payload.assistant_session_id,
        organization_id=context.organization_id,
        requested_query=payload.requested_query,
        selected_search_mode=payload.selected_search_mode,
        runtime_metadata=payload.runtime_metadata,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assistant or assistant session not found")
    if result.get("blocking_issues"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result
