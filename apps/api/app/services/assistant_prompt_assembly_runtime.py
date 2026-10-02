"""Assistant Prompt Assembly runtime."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantContextPackage, AssistantPromptPackage
from app.repositories.assistant import AssistantRepository
from app.services.assistant_prompt_assembly_gateway import (
    build_assistant_prompt_assembly_gateway,
    build_assistant_prompt_assembly_health,
)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4) if text else 0


def _system_prompt() -> str:
    return (
        "You are a retrieval-grounded assistant for a generic SaaS platform. "
        "Use only the provided context and citations. If the context is insufficient, "
        "state that the available evidence is insufficient."
    )


def _assistant_instructions() -> str:
    return (
        "Answer only from the assembled context. Preserve citation references. "
        "Do not use external knowledge, tools, workflows, autonomous actions, or unstated assumptions."
    )


def _assembled_context(ordered_context: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for item in ordered_context:
        index = item.get("context_index")
        citation_id = item.get("citation_id") or "citation:unavailable"
        text = str(item.get("text") or "")
        sections.append(f"[Context {index}] citation={citation_id}\n{text}")
    return "\n\n".join(sections)


def _citation_section(ordered_citations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in ordered_citations:
        citation_id = item.get("citation_id") or "citation:unavailable"
        source = item.get("source") or "knowledge_chunk"
        chunk = item.get("knowledge_chunk_id") or item.get("published_chunk_id") or item.get("chunk_index")
        lines.append(f"- {citation_id}: source={source}; chunk={chunk}")
    return "\n".join(lines)


def assistant_prompt_package_to_dict(record: AssistantPromptPackage) -> dict[str, Any]:
    return {
        "prompt_package_id": str(record.prompt_package_id),
        "context_package_id": str(record.context_package_id),
        "assistant_id": str(record.assistant_id),
        "assistant_session_id": str(record.assistant_session_id) if record.assistant_session_id else None,
        "package_status": record.package_status,
        "system_prompt": record.system_prompt,
        "assistant_instructions": record.assistant_instructions,
        "assembled_context": record.assembled_context,
        "citation_section": record.citation_section,
        "estimated_prompt_tokens": int(record.estimated_prompt_tokens or 0),
        "prompt_size_bytes": int(record.prompt_size_bytes or 0),
        "prompt_metadata": record.prompt_metadata or {},
        "llm_ready": bool(record.llm_ready),
        "llm_invoked": bool(record.llm_invoked),
        "answer_generated": bool(record.answer_generated),
        "assistant_prompt_assembly_prepared": True,
        "prompt_package_created": True,
        "system_prompt_created": bool(record.system_prompt),
        "assistant_instructions_created": bool(record.assistant_instructions),
        "assembled_context_created": bool(record.assembled_context),
        "citations_attached": bool(record.citation_section),
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def build_assistant_prompt_assembly_runtime(
    db: Session,
    *,
    context_package_id: str,
    organization_id: uuid.UUID | None = None,
    prompt_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    scoped_repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(context_package_id))
    except (TypeError, ValueError):
        return None
    scoped_artifact = scoped_repository.get_scoped_artifact(
        AssistantContextPackage,
        AssistantContextPackage.context_package_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if scoped_artifact is None or (scoped_artifact.ownership_scope == "organization" and organization_id is None):
        return None
    gateway = build_assistant_prompt_assembly_gateway(
        db, context_package_id=context_package_id, prompt_metadata=prompt_metadata
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_prompt_assembly_schema_version": "1",
            "assistant_prompt_assembly_prepared": False,
            "assistant_prompt_assembly_gateway": gateway,
            "context_package_created": False,
            "prompt_package_created": False,
            "system_prompt_created": False,
            "assistant_instructions_created": False,
            "assembled_context_created": False,
            "citations_attached": False,
            "llm_ready": False,
            "llm_invoked": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = AssistantRepository(db)
    context_package = scoped_artifact
    if context_package is None:
        return None
    system_prompt = _system_prompt()
    assistant_instructions = _assistant_instructions()
    assembled_context = _assembled_context(list(context_package.ordered_context or []))
    citation_section = _citation_section(list(context_package.ordered_citations or []))
    full_prompt = "\n\n".join([system_prompt, assistant_instructions, assembled_context, citation_section])
    estimated_prompt_tokens = _estimate_tokens(full_prompt)
    prompt_size_bytes = len(full_prompt.encode("utf-8"))
    prompt_package = repository.create_prompt_package(
        context_package_id=context_package.context_package_id,
        assistant_id=context_package.assistant_id,
        assistant_session_id=context_package.assistant_session_id,
        package_status="created",
        system_prompt=system_prompt,
        assistant_instructions=assistant_instructions,
        assembled_context=assembled_context,
        citation_section=citation_section,
        estimated_prompt_tokens=estimated_prompt_tokens,
        prompt_size_bytes=prompt_size_bytes,
        prompt_metadata={
            **dict(prompt_metadata or {}),
            "assistant_prompt_assembly_prepared": True,
            "context_package_created": True,
            "prompt_package_created": True,
            "system_prompt_created": bool(system_prompt),
            "assistant_instructions_created": bool(assistant_instructions),
            "assembled_context_created": bool(assembled_context),
            "citations_attached": bool(citation_section),
            "llm_ready": True,
            "llm_invoked": False,
            "answer_generated": False,
            "tool_called": False,
            "workflow_executed": False,
            "external_action_called": False,
            "autonomous_execution": False,
            "postgresql_source_of_truth": True,
        },
        llm_ready=True,
        llm_invoked=False,
        answer_generated=False,
    )
    db.commit()
    payload = {
        "assistant_prompt_assembly_schema_version": "1",
        "assistant_prompt_assembly_prepared": True,
        "assistant_prompt_assembly_gateway": gateway,
        "assistant_prompt_package": assistant_prompt_package_to_dict(prompt_package),
        "prompt_package_id": str(prompt_package.prompt_package_id),
        "context_package_id": str(context_package.context_package_id),
        "assistant_id": str(context_package.assistant_id),
        "assistant_session_id": str(context_package.assistant_session_id)
        if context_package.assistant_session_id
        else None,
        "context_package_created": True,
        "prompt_package_created": True,
        "system_prompt_created": bool(system_prompt),
        "assistant_instructions_created": bool(assistant_instructions),
        "assembled_context_created": bool(assembled_context),
        "citations_attached": bool(citation_section),
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "prompt_size_bytes": prompt_size_bytes,
        "llm_ready": True,
        "llm_invoked": False,
        "answer_generated": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": bool(system_prompt and assistant_instructions and assembled_context and citation_section),
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-prompt-assembly:{prompt_package.prompt_package_id}",
            artifact_id=None,
            runtime_outputs={"assistant_prompt_assembly": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_prompt_package(db: Session, prompt_package_id: str) -> dict[str, Any] | None:
    try:
        prompt_package_uuid = uuid.UUID(str(prompt_package_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_prompt_package(prompt_package_uuid)
    return assistant_prompt_package_to_dict(record) if record is not None else None


__all__ = [
    "assistant_prompt_package_to_dict",
    "build_assistant_prompt_assembly_health",
    "build_assistant_prompt_assembly_runtime",
    "read_assistant_prompt_package",
]
