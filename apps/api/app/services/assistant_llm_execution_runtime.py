"""Assistant LLM Execution runtime."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantLlmExecution, AssistantLlmInvocationPlan
from app.repositories.assistant import AssistantRepository
from app.services.assistant_llm_execution_contracts import (
    LOCAL_MOCK_CALL_MODE,
    LOCAL_MOCK_MODEL_NAME,
    LOCAL_MOCK_PROVIDER_NAME,
    LOCAL_MOCK_PROVIDER_TYPE,
)
from app.services.assistant_llm_execution_gateway import (
    build_assistant_llm_execution_gateway,
    build_assistant_llm_execution_health,
)
from app.services.assistant_locale import grounded_response, no_evidence_message
from app.services.assistant_run_recovery_runtime import lock_current_provider_claim


def _estimate_tokens(text: str | None) -> int:
    value = text or ""
    return max(1, (len(value) + 3) // 4) if value else 0


@dataclass(frozen=True)
class AssistantLlmProviderExecutionResult:
    raw_output_text: str
    raw_output_metadata: dict[str, Any]


class AssistantLlmExecutionProvider(Protocol):
    provider_type: str
    provider_name: str
    model_name: str
    provider_call_mode: str

    def execute(
        self,
        *,
        prompt_package_id: str,
        system_prompt: str,
        assistant_instructions: str,
        assembled_context: str,
        citation_section: str,
        locale: object = "en",
    ) -> AssistantLlmProviderExecutionResult: ...


class DeterministicLocalMockLlmProvider:
    provider_type = LOCAL_MOCK_PROVIDER_TYPE
    provider_name = LOCAL_MOCK_PROVIDER_NAME
    model_name = LOCAL_MOCK_MODEL_NAME
    provider_call_mode = LOCAL_MOCK_CALL_MODE

    @staticmethod
    def _grounded_response(assembled_context: str, locale: object = "en") -> str:
        context_pattern = re.compile(
            r"\[Context\s+\d+\]\s+citation=(citation:[A-Za-z0-9_.:-]+)\s*\n(.*?)(?=\n\n\[Context\s+\d+\]|\Z)",
            re.DOTALL,
        )
        evidence: list[str] = []
        for citation_id, context_text in context_pattern.findall(assembled_context or ""):
            normalized = " ".join(context_text.replace("<mark>", "").replace("</mark>", "").split())
            if not normalized:
                continue
            preview = normalized[:420].rstrip()
            if len(normalized) > len(preview):
                preview = f"{preview}…"
            evidence.append(f"- {preview} [{citation_id}]")
            if len(evidence) == 3:
                break
        if not evidence:
            return no_evidence_message(locale)
        return grounded_response(locale, evidence)

    def execute(
        self,
        *,
        prompt_package_id: str,
        system_prompt: str,
        assistant_instructions: str,
        assembled_context: str,
        citation_section: str,
        locale: object = "en",
    ) -> AssistantLlmProviderExecutionResult:
        source = "\n\n".join(
            [prompt_package_id, system_prompt, assistant_instructions, assembled_context, citation_section]
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        raw_output = self._grounded_response(assembled_context, locale)
        return AssistantLlmProviderExecutionResult(
            raw_output_text=raw_output,
            raw_output_metadata={
                "mock_digest": digest,
                "provider_boundary": "local_process",
                "network_used": False,
                "deterministic": True,
            },
        )


class AssistantLlmProviderRuntimeAdapter:
    def __init__(self, provider: AssistantLlmExecutionProvider) -> None:
        self.provider = provider

    def execute(
        self,
        *,
        prompt_package_id: str,
        system_prompt: str,
        assistant_instructions: str,
        assembled_context: str,
        citation_section: str,
        locale: object = "en",
    ) -> AssistantLlmProviderExecutionResult:
        return self.provider.execute(
            prompt_package_id=prompt_package_id,
            system_prompt=system_prompt,
            assistant_instructions=assistant_instructions,
            assembled_context=assembled_context,
            citation_section=citation_section,
            locale=locale,
        )


def _local_mock_adapter() -> AssistantLlmProviderRuntimeAdapter:
    return AssistantLlmProviderRuntimeAdapter(DeterministicLocalMockLlmProvider())


def assistant_llm_execution_to_dict(record: AssistantLlmExecution) -> dict[str, Any]:
    return {
        "llm_execution_id": str(record.llm_execution_id),
        "gateway_id": str(record.gateway_id),
        "prompt_package_id": str(record.prompt_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "provider_type": record.provider_type,
        "provider_name": record.provider_name,
        "model_name": record.model_name,
        "execution_status": record.execution_status,
        "execution_allowed": bool(record.execution_allowed),
        "provider_called": bool(record.provider_called),
        "provider_call_mode": record.provider_call_mode,
        "request_payload_metadata": record.request_payload_metadata or {},
        "raw_output_text": record.raw_output_text,
        "raw_output_metadata": record.raw_output_metadata or {},
        "prompt_tokens_estimated": int(record.prompt_tokens_estimated or 0),
        "completion_tokens_estimated": int(record.completion_tokens_estimated or 0),
        "total_tokens_estimated": int(record.total_tokens_estimated or 0),
        "latency_ms": record.latency_ms,
        "provider_call_started_at": record.provider_call_started_at.isoformat()
        if record.provider_call_started_at
        else None,
        "provider_call_finished_at": record.provider_call_finished_at.isoformat()
        if record.provider_call_finished_at
        else None,
        "cost_metadata": record.cost_metadata or {},
        "citation_verification_completed": bool(record.citation_verification_completed),
        "final_response_created": bool(record.final_response_created),
        "tool_called": bool(record.tool_called),
        "workflow_executed": bool(record.workflow_executed),
        "external_action_called": bool(record.external_action_called),
        "autonomous_execution": bool(record.autonomous_execution),
        "assistant_llm_execution_prepared": True,
        "llm_gateway_created": True,
        "llm_execution_created": True,
        "raw_output_created": bool(record.raw_output_text),
        "raw_output_persisted": bool(record.raw_output_text),
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


_CLAIM_CONSTRAINT = "uq_ai_assistant_llm_executions_gateway_claim"
_NON_AUTHORITATIVE_METADATA = {
    "correlation_id",
    "trace_id",
    "request_id",
    "timestamp",
    "created_at",
    "updated_at",
    "idempotency_input_fingerprint",
    "gateway_id",
    "prompt_package_id",
    "provider_call_mode",
    "chat_runtime_prepared",
    "recovery_generation",
}


def _authoritative_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _authoritative_metadata(item) for key, item in value.items() if key not in _NON_AUTHORITATIVE_METADATA
        }
    if isinstance(value, list):
        return [_authoritative_metadata(item) for item in value]
    return value


def _input_fingerprint(
    plan: AssistantLlmInvocationPlan,
    prompt: Any,
    metadata: dict[str, Any] | None,
) -> str:
    authoritative_metadata = _authoritative_metadata(dict(metadata or {}))
    authoritative_metadata.setdefault("locale", "en")
    payload = {
        "gateway_id": str(plan.gateway_id),
        "prompt_package_id": str(plan.prompt_package_id),
        "assistant_id": str(plan.assistant_id),
        "assistant_session_id": str(plan.assistant_session_id) if plan.assistant_session_id else None,
        "organization_id": str(plan.organization_id) if plan.organization_id else None,
        "ownership_scope": plan.ownership_scope,
        "plan_provider": [plan.provider_type, plan.provider_name, plan.model_name],
        "execution_provider": [LOCAL_MOCK_PROVIDER_TYPE, LOCAL_MOCK_PROVIDER_NAME, LOCAL_MOCK_MODEL_NAME],
        "inference": {
            "temperature": plan.planned_temperature,
            "max_tokens": plan.planned_max_tokens,
            "top_p": plan.planned_top_p,
            "stop_sequences": plan.planned_stop_sequences or [],
            "seed": plan.planned_seed,
            "timeout": plan.planned_timeout,
        },
        "prompt": [
            prompt.system_prompt,
            prompt.assistant_instructions,
            prompt.assembled_context,
            prompt.citation_section,
        ],
        "metadata": authoritative_metadata,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _execution_problem(
    gateway_id: uuid.UUID, code: str, message: str, *, gateway: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "assistant_llm_execution_schema_version": "1",
        "assistant_llm_execution_prepared": False,
        "assistant_llm_execution_gateway": gateway,
        "gateway_id": str(gateway_id),
        "llm_execution_created": False,
        "provider_called": False,
        "passed": False,
        "postgresql_source_of_truth": True,
        "blocking_issues": [
            {
                "code": code,
                "severity": "blocking",
                "component": "assistant_llm_execution_runtime",
                "item_id": str(gateway_id),
                "message": message,
            }
        ],
        "warnings": [],
    }


def _execution_payload(
    record: AssistantLlmExecution,
    *,
    gateway: dict[str, Any] | None,
    replay: bool,
) -> dict[str, Any]:
    return {
        "assistant_llm_execution_schema_version": "1",
        "assistant_llm_execution_prepared": True,
        "assistant_llm_execution_gateway": gateway,
        "assistant_llm_execution": assistant_llm_execution_to_dict(record),
        "llm_execution_id": str(record.llm_execution_id),
        "gateway_id": str(record.gateway_id),
        "prompt_package_id": str(record.prompt_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "llm_gateway_created": True,
        "llm_execution_created": not replay,
        "idempotent_replay": replay,
        "provider_type": record.provider_type,
        "provider_name": record.provider_name,
        "model_name": record.model_name,
        "execution_status": record.execution_status,
        "execution_allowed": bool(record.execution_allowed),
        "provider_called": bool(record.provider_called),
        "provider_call_mode": record.provider_call_mode,
        "raw_output_created": record.raw_output_text is not None,
        "raw_output_persisted": record.raw_output_text is not None,
        "prompt_tokens_estimated": int(record.prompt_tokens_estimated or 0),
        "completion_tokens_estimated": int(record.completion_tokens_estimated or 0),
        "total_tokens_estimated": int(record.total_tokens_estimated or 0),
        "latency_ms": record.latency_ms,
        "citation_verification_completed": bool(record.citation_verification_completed),
        "final_response_created": bool(record.final_response_created),
        "tool_called": bool(record.tool_called),
        "workflow_executed": bool(record.workflow_executed),
        "external_action_called": bool(record.external_action_called),
        "autonomous_execution": bool(record.autonomous_execution),
        "postgresql_source_of_truth": True,
        "passed": True,
        "blocking_issues": [],
        "warnings": list((gateway or {}).get("warnings") or []),
    }


def _existing_execution(
    repository: AssistantRepository,
    plan: AssistantLlmInvocationPlan,
    prompt: Any,
    fingerprint: str,
    *,
    allow_prepared_resume: bool = False,
) -> dict[str, Any] | None:
    rows = repository.list_llm_executions_for_plan(plan.gateway_id)
    if not rows:
        return None
    if len(rows) != 1:
        return _execution_problem(
            plan.gateway_id, "llm_provider_claim_ambiguous", "Multiple persisted executions claim this plan."
        )
    record = rows[0]
    metadata = record.request_payload_metadata or {}
    stored_fingerprint = metadata.get("idempotency_input_fingerprint")
    if not stored_fingerprint:
        return _execution_problem(
            plan.gateway_id,
            "llm_provider_legacy_claim_unverifiable",
            "Historical execution lacks authoritative input evidence; no automatic replay is allowed.",
        )
    if (
        record.gateway_id != plan.gateway_id
        or record.prompt_package_id != plan.prompt_package_id
        or record.assistant_id != plan.assistant_id
        or record.assistant_session_id != plan.assistant_session_id
        or record.organization_id != plan.organization_id
        or record.ownership_scope != plan.ownership_scope
        or record.provider_type != LOCAL_MOCK_PROVIDER_TYPE
        or record.provider_name != LOCAL_MOCK_PROVIDER_NAME
        or record.model_name != LOCAL_MOCK_MODEL_NAME
        or record.provider_call_mode != LOCAL_MOCK_CALL_MODE
        or stored_fingerprint != fingerprint
    ):
        return _execution_problem(
            plan.gateway_id, "llm_provider_input_conflict", "Persisted execution has different input or lineage."
        )
    if record.execution_status == "completed" and record.raw_output_text is not None:
        return _execution_payload(record, gateway=None, replay=True)
    if (
        allow_prepared_resume
        and record.execution_status == "prepared"
        and record.provider_call_started_at is None
        and record.provider_call_finished_at is None
    ):
        return None
    if record.execution_status in {"prepared", "running"}:
        return _execution_problem(
            plan.gateway_id,
            "llm_provider_claim_in_progress",
            "Provider claim exists; dispatch outcome is not yet authoritative. No automatic replay is allowed.",
        )
    return _execution_problem(
        plan.gateway_id,
        "llm_provider_attempt_failed",
        "A prior provider attempt is persisted. An explicit new operation is required for another attempt.",
    )


def build_assistant_llm_execution_runtime(
    db: Session,
    *,
    gateway_id: str,
    organization_id: uuid.UUID | None = None,
    request_payload_metadata: dict[str, Any] | None = None,
    runtime_run_claim_generation: int | None = None,
    resume_prepared_claim: bool = False,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(gateway_id))
    except (TypeError, ValueError):
        return None
    plan = repository.get_scoped_artifact(
        AssistantLlmInvocationPlan,
        AssistantLlmInvocationPlan.gateway_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if plan is None or (plan.ownership_scope == "organization" and organization_id is None):
        return None
    prompt = repository.get_prompt_package(plan.prompt_package_id)
    if prompt is None:
        return None
    if (
        prompt.assistant_id != plan.assistant_id
        or prompt.assistant_session_id != plan.assistant_session_id
        or prompt.organization_id != plan.organization_id
        or prompt.ownership_scope != plan.ownership_scope
    ):
        return _execution_problem(plan.gateway_id, "llm_provider_lineage_conflict", "Plan and prompt lineage differ.")
    fingerprint = _input_fingerprint(plan, prompt, request_payload_metadata)
    existing = _existing_execution(repository, plan, prompt, fingerprint, allow_prepared_resume=resume_prepared_claim)
    if existing is not None:
        return existing
    prepared_rows = repository.list_llm_executions_for_plan(plan.gateway_id) if resume_prepared_claim else []
    if resume_prepared_claim and len(prepared_rows) != 1:
        return _execution_problem(
            plan.gateway_id,
            "llm_provider_prepared_claim_missing",
            "Persisted prepared provider claim is unavailable for recovery.",
        )

    gateway = build_assistant_llm_execution_gateway(
        db, gateway_id=gateway_id, request_payload_metadata=request_payload_metadata
    )
    if gateway.get("blocking_issues"):
        return {
            **_execution_problem(plan.gateway_id, "llm_provider_gateway_blocked", "LLM execution gateway is blocked."),
            "assistant_llm_execution_gateway": gateway,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }

    try:
        if resume_prepared_claim:
            record = prepared_rows[0]
        else:
            with db.begin_nested():
                record = repository.create_llm_execution(
                    gateway_id=plan.gateway_id,
                    prompt_package_id=prompt.prompt_package_id,
                    assistant_id=plan.assistant_id,
                    assistant_session_id=plan.assistant_session_id,
                    provider_type=LOCAL_MOCK_PROVIDER_TYPE,
                    provider_name=LOCAL_MOCK_PROVIDER_NAME,
                    model_name=LOCAL_MOCK_MODEL_NAME,
                    execution_status="prepared",
                    execution_allowed=True,
                    provider_called=False,
                    provider_call_mode=LOCAL_MOCK_CALL_MODE,
                    request_payload_metadata={
                        **dict(request_payload_metadata or {}),
                        "gateway_id": str(plan.gateway_id),
                        "prompt_package_id": str(prompt.prompt_package_id),
                        "provider_call_mode": LOCAL_MOCK_CALL_MODE,
                        "idempotency_input_fingerprint": fingerprint,
                    },
                    raw_output_text=None,
                    raw_output_metadata={},
                )
        db.commit()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_ai_assistant_llm_executions_runtime_claim":
            return _execution_problem(
                plan.gateway_id,
                "llm_provider_run_claim_conflict",
                "Another persisted provider claim already belongs to this RuntimeRun.",
            )
        if constraint != _CLAIM_CONSTRAINT:
            raise
        winner = _existing_execution(repository, plan, prompt, fingerprint)
        if winner is None:
            raise
        return winner

    if runtime_run_claim_generation is not None:
        metadata = dict(request_payload_metadata or {})
        raw_run_id = metadata.get("assistant_run_id")
        if not raw_run_id or plan.organization_id is None or plan.assistant_session_id is None:
            return _execution_problem(
                plan.gateway_id, "runtime_run_claim_lineage_missing", "RuntimeRun claim lineage is unavailable."
            )
        if not lock_current_provider_claim(
            db,
            run_id=uuid.UUID(str(raw_run_id)),
            organization_id=plan.organization_id,
            assistant_id=plan.assistant_id,
            assistant_session_id=plan.assistant_session_id,
            generation=runtime_run_claim_generation,
        ):
            db.commit()
            return _execution_problem(
                plan.gateway_id,
                "runtime_run_claim_stale",
                "RuntimeRun claim is expired or superseded; provider dispatch is fenced.",
            )
    record.execution_status = "running"
    record.provider_call_started_at = (
        db.scalar(select(func.clock_timestamp())) if runtime_run_claim_generation is not None else datetime.now(UTC)
    )
    db.add(record)
    db.commit()
    started = time.perf_counter()
    try:
        provider_result = _local_mock_adapter().execute(
            prompt_package_id=str(prompt.prompt_package_id),
            system_prompt=prompt.system_prompt,
            assistant_instructions=prompt.assistant_instructions,
            assembled_context=prompt.assembled_context,
            citation_section=prompt.citation_section,
            locale=(request_payload_metadata or {}).get("locale", "en"),
        )
    except Exception:
        record.execution_status = "failed"
        record.provider_called = True
        record.provider_call_finished_at = datetime.now(UTC)
        record.raw_output_metadata = {"provider_outcome": "failed"}
        db.add(record)
        db.commit()
        return _execution_problem(
            plan.gateway_id,
            "llm_provider_attempt_failed",
            "Provider attempt failed; no automatic replay is allowed.",
        )
    raw_output_text = provider_result.raw_output_text
    prompt_text = "\n\n".join(
        [prompt.system_prompt, prompt.assistant_instructions, prompt.assembled_context, prompt.citation_section]
    )
    record.execution_status = "completed"
    record.provider_called = True
    record.provider_call_finished_at = datetime.now(UTC)
    record.raw_output_text = raw_output_text
    record.raw_output_metadata = provider_result.raw_output_metadata
    record.prompt_tokens_estimated = _estimate_tokens(prompt_text)
    record.completion_tokens_estimated = _estimate_tokens(raw_output_text)
    record.total_tokens_estimated = record.prompt_tokens_estimated + record.completion_tokens_estimated
    record.latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    record.cost_metadata = {"cost_calculated": False, "cost_amount": None, "currency": None}
    db.add(record)
    db.commit()
    payload = _execution_payload(record, gateway=gateway, replay=False)
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-llm-execution:{record.llm_execution_id}",
            artifact_id=None,
            runtime_outputs={"assistant_llm_execution": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_llm_execution(db: Session, llm_execution_id: str) -> dict[str, Any] | None:
    try:
        execution_uuid = uuid.UUID(str(llm_execution_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_llm_execution(execution_uuid)
    return assistant_llm_execution_to_dict(record) if record is not None else None


__all__ = [
    "assistant_llm_execution_to_dict",
    "build_assistant_llm_execution_health",
    "build_assistant_llm_execution_runtime",
    "read_assistant_llm_execution",
]
