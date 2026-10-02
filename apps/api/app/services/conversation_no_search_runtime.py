from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import ConversationTurn
from app.repositories.assistant import AssistantRepository
from app.services.conversation_interaction_plan_runtime import resolve_interaction_execution_directive


class ConversationNoSearchExecutionError(RuntimeError):
    """Raised when persisted evidence cannot authorize a no-Search execution."""


def _normalize_referenced_turn_ids(values: list[str] | None) -> list[uuid.UUID]:
    normalized: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in list(values or []):
        try:
            turn_id = uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ConversationNoSearchExecutionError("persisted referenced turn id is invalid") from exc
        if turn_id in seen:
            continue
        seen.add(turn_id)
        normalized.append(turn_id)
    return normalized


def _load_referenced_conversation_turns(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID,
    referenced_turn_ids: list[uuid.UUID],
) -> list[ConversationTurn]:
    if not referenced_turn_ids:
        return []
    records = list(
        db.scalars(
            select(ConversationTurn).where(
                ConversationTurn.organization_id == organization_id,
                ConversationTurn.ownership_scope == "organization",
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.conversation_turn_id.in_(referenced_turn_ids),
            )
        ).all()
    )
    by_id = {record.conversation_turn_id: record for record in records}
    missing = [turn_id for turn_id in referenced_turn_ids if turn_id not in by_id]
    if missing:
        raise ConversationNoSearchExecutionError(
            "persisted referenced conversation evidence is unavailable in the authorized organization scope"
        )
    return [by_id[turn_id] for turn_id in referenced_turn_ids]


def _turn_content(turn: ConversationTurn) -> str:
    if turn.turn_role in {"assistant", "tool"}:
        return str(turn.output_text or turn.input_text or "").strip()
    return str(turn.input_text or turn.output_text or "").strip()


def _normalize_instruction(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", without_marks.casefold()).strip(" ¿?¡!.,;:")


def _deterministic_refinement_mode(instruction: str) -> str | None:
    normalized = _normalize_instruction(instruction)
    shorten_patterns = (
        r"^(?:acortalo|abrevia|hazlo breve|hazlo mas breve|hazlo mas corto)\b",
        r"^(?:mas corto|mas breve|menos largo)\b",
        r"^(?:shorten|make it shorter|make it brief)\b",
    )
    if any(re.search(pattern, normalized) for pattern in shorten_patterns):
        return "shorten"
    return None


def _shorten_persisted_response(value: str) -> str:
    words = str(value or "").split()
    if len(words) <= 24:
        return " ".join(words)
    target = max(24, len(words) // 2)
    shortened = " ".join(words[:target]).rstrip(" ,;:")
    return f"{shortened}…"


def build_persisted_citation_response_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> dict[str, Any]:
    """Resolve citation_request strictly from persisted conversation evidence, without Search."""
    directive = resolve_interaction_execution_directive(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if directive.planned_action != "reuse_persisted_citations":
        raise ConversationNoSearchExecutionError(
            f"persisted interaction plan does not authorize citation reuse: {directive.planned_action}"
        )
    if directive.enterprise_search_required:
        raise ConversationNoSearchExecutionError("citation reuse cannot execute with Enterprise Search enabled")

    repository = AssistantRepository(db)
    decision = repository.get_scoped_conversation_interaction_decision(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if decision is None:
        raise ConversationNoSearchExecutionError("persisted interaction decision is unavailable")
    if decision.intent != "citation_request":
        raise ConversationNoSearchExecutionError("persisted interaction decision intent is inconsistent")

    referenced_turn_ids = _normalize_referenced_turn_ids(list(decision.referenced_turn_ids or []))
    referenced_turns = _load_referenced_conversation_turns(
        db,
        organization_id=organization_id,
        conversation_id=decision.conversation_id,
        referenced_turn_ids=referenced_turn_ids,
    )

    ordered_citations: list[dict[str, Any]] = []
    evidence_turn_ids: list[str] = []
    for turn in referenced_turns:
        evidence_turn_ids.append(str(turn.conversation_turn_id))
        ordered_citations.extend(dict(citation) for citation in list(turn.ordered_citations or []))

    response_text = (
        "No persisted citations are available for the referenced response."
        if not ordered_citations
        else "Persisted citations from the referenced response are available in ordered_citations."
    )
    return {
        "conversation_no_search_runtime_schema_version": "1",
        "conversation_no_search_runtime_prepared": True,
        "interaction_plan_id": str(directive.interaction_plan_id),
        "organization_id": str(organization_id),
        "conversation_id": str(decision.conversation_id),
        "conversation_turn_id": str(conversation_turn_id),
        "planned_action": directive.planned_action,
        "intent": decision.intent,
        "referenced_turn_ids": [str(turn_id) for turn_id in referenced_turn_ids],
        "evidence_turn_ids": evidence_turn_ids,
        "response_text": response_text,
        "response_format": "markdown",
        "ordered_citations": ordered_citations,
        "citation_count": len(ordered_citations),
        "enterprise_search_required": False,
        "enterprise_search_bypassed": True,
        "generation_required": False,
        "deterministic_response": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": [],
    }


def build_conversation_summary_response_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> dict[str, Any]:
    """Generate a deterministic summary from persisted conversation evidence, without Search."""
    directive = resolve_interaction_execution_directive(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if directive.planned_action != "summarize_conversation_evidence":
        raise ConversationNoSearchExecutionError(
            f"persisted interaction plan does not authorize conversation summary: {directive.planned_action}"
        )
    if directive.enterprise_search_required:
        raise ConversationNoSearchExecutionError("conversation summary cannot execute with Enterprise Search enabled")

    repository = AssistantRepository(db)
    decision = repository.get_scoped_conversation_interaction_decision(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if decision is None:
        raise ConversationNoSearchExecutionError("persisted interaction decision is unavailable")
    if decision.intent != "conversation_summary":
        raise ConversationNoSearchExecutionError("persisted interaction decision intent is inconsistent")

    referenced_turn_ids = _normalize_referenced_turn_ids(list(decision.referenced_turn_ids or []))
    referenced_turns = _load_referenced_conversation_turns(
        db,
        organization_id=organization_id,
        conversation_id=decision.conversation_id,
        referenced_turn_ids=referenced_turn_ids,
    )

    evidence_turn_ids: list[str] = []
    summary_lines: list[str] = []
    ordered_citations: list[dict[str, Any]] = []
    for turn in referenced_turns:
        content = _turn_content(turn)
        evidence_turn_ids.append(str(turn.conversation_turn_id))
        if content:
            summary_lines.append(f"- {turn.turn_role}: {content}")
        ordered_citations.extend(dict(citation) for citation in list(turn.ordered_citations or []))

    response_text = (
        "No persisted conversation evidence is available to summarize."
        if not summary_lines
        else "Conversation summary from persisted evidence:\n" + "\n".join(summary_lines)
    )
    return {
        "conversation_no_search_runtime_schema_version": "1",
        "conversation_no_search_runtime_prepared": True,
        "interaction_plan_id": str(directive.interaction_plan_id),
        "organization_id": str(organization_id),
        "conversation_id": str(decision.conversation_id),
        "conversation_turn_id": str(conversation_turn_id),
        "planned_action": directive.planned_action,
        "intent": decision.intent,
        "referenced_turn_ids": [str(turn_id) for turn_id in referenced_turn_ids],
        "evidence_turn_ids": evidence_turn_ids,
        "response_text": response_text,
        "response_format": "markdown",
        "ordered_citations": ordered_citations,
        "citation_count": len(ordered_citations),
        "enterprise_search_required": False,
        "enterprise_search_bypassed": True,
        "generation_required": bool(directive.generation_required),
        "generation_mode": "deterministic_persisted_evidence",
        "deterministic_response": True,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": [],
    }


def build_response_refinement_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID,
    conversation_turn_id: uuid.UUID,
) -> dict[str, Any]:
    """Refine a persisted prior assistant response without Search when safely deterministic."""
    directive = resolve_interaction_execution_directive(
        db,
        organization_id=organization_id,
        conversation_turn_id=conversation_turn_id,
    )
    if directive.planned_action != "refine_prior_response":
        raise ConversationNoSearchExecutionError(
            f"persisted interaction plan does not authorize response refinement: {directive.planned_action}"
        )
    if directive.enterprise_search_required:
        raise ConversationNoSearchExecutionError("response refinement cannot execute with Enterprise Search enabled")

    repository = AssistantRepository(db)
    decision = repository.get_scoped_conversation_interaction_decision(
        conversation_turn_id=conversation_turn_id,
        organization_id=organization_id,
    )
    if decision is None:
        raise ConversationNoSearchExecutionError("persisted interaction decision is unavailable")
    if decision.intent != "response_refinement":
        raise ConversationNoSearchExecutionError("persisted interaction decision intent is inconsistent")

    current_turn = repository.get_scoped_conversation_turn(
        conversation_turn_id,
        organization_id=organization_id,
    )
    if current_turn is None or current_turn.turn_role != "user":
        raise ConversationNoSearchExecutionError("persisted refinement instruction turn is unavailable")
    if current_turn.conversation_id != decision.conversation_id:
        raise ConversationNoSearchExecutionError("persisted refinement instruction lineage is inconsistent")

    referenced_turn_ids = _normalize_referenced_turn_ids(list(decision.referenced_turn_ids or []))
    referenced_turns = _load_referenced_conversation_turns(
        db,
        organization_id=organization_id,
        conversation_id=decision.conversation_id,
        referenced_turn_ids=referenced_turn_ids,
    )
    if len(referenced_turns) != 1 or referenced_turns[0].turn_role != "assistant":
        raise ConversationNoSearchExecutionError("response refinement requires one persisted prior assistant response")

    prior_turn = referenced_turns[0]
    prior_response = _turn_content(prior_turn)
    if not prior_response:
        raise ConversationNoSearchExecutionError("persisted prior assistant response is empty")
    instruction = str(current_turn.input_text or "").strip()
    mode = _deterministic_refinement_mode(instruction)
    ordered_citations = [dict(citation) for citation in list(prior_turn.ordered_citations or [])]

    if mode == "shorten":
        response_text: str | None = _shorten_persisted_response(prior_response)
        configured_generation_required = False
        deterministic_response = True
        generation_mode = "deterministic_shorten_persisted_response"
    else:
        response_text = None
        configured_generation_required = True
        deterministic_response = False
        generation_mode = "configured_generation_required"

    return {
        "conversation_no_search_runtime_schema_version": "1",
        "conversation_no_search_runtime_prepared": True,
        "interaction_plan_id": str(directive.interaction_plan_id),
        "organization_id": str(organization_id),
        "conversation_id": str(decision.conversation_id),
        "conversation_turn_id": str(conversation_turn_id),
        "planned_action": directive.planned_action,
        "intent": decision.intent,
        "referenced_turn_ids": [str(turn_id) for turn_id in referenced_turn_ids],
        "evidence_turn_ids": [str(prior_turn.conversation_turn_id)],
        "refinement_instruction": instruction,
        "refinement_mode": mode,
        "response_text": response_text,
        "response_format": str(prior_turn.response_format or "markdown"),
        "ordered_citations": ordered_citations,
        "citation_count": len(ordered_citations),
        "enterprise_search_required": False,
        "enterprise_search_bypassed": True,
        "generation_required": bool(directive.generation_required),
        "generation_mode": generation_mode,
        "configured_generation_required": configured_generation_required,
        "deterministic_response": deterministic_response,
        "postgresql_source_of_truth": True,
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "passed": True,
        "blocking_issues": [],
        "warnings": [],
    }
