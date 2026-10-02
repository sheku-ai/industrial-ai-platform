"""Assistant Citation Verification runtime."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantCitationVerification, AssistantLlmExecution
from app.repositories.assistant import AssistantRepository
from app.services.assistant_citation_verification_gateway import (
    build_assistant_citation_verification_gateway,
    build_assistant_citation_verification_health,
)
from app.services.assistant_execution_evidence_reader import read_assistant_execution_evidence_v1

CITATION_PATTERN = re.compile(r"citation:[A-Za-z0-9_.:-]+")
CITATION_IDENTITY_CONSTRAINT = "uq_ai_assistant_citation_verifications_llm_execution"


def _citation_identity_conflict(llm_execution_id: uuid.UUID) -> dict[str, Any]:
    return {
        "assistant_citation_verification_schema_version": "1",
        "assistant_citation_verification_prepared": False,
        "citation_runtime_created": False,
        "passed": False,
        "blocking_issues": [{
            "code": "citation_verification_idempotency_conflict",
            "severity": "blocking",
            "component": "assistant_citation_verification_runtime",
            "item_id": str(llm_execution_id),
            "message": "Persisted citation verification differs from authoritative LLM evidence.",
        }],
        "warnings": [],
    }


def _citation_matches_pipeline(
    verification: AssistantCitationVerification,
    execution: AssistantLlmExecution,
    *,
    assistant_runtime_id: uuid.UUID | None,
    context_package_id: uuid.UUID,
    summary: dict[str, Any],
) -> bool:
    return bool(
        verification.llm_execution_id == execution.llm_execution_id
        and verification.prompt_package_id == execution.prompt_package_id
        and verification.context_package_id == context_package_id
        and verification.assistant_runtime_id == assistant_runtime_id
        and verification.organization_id == execution.organization_id
        and verification.ownership_scope == execution.ownership_scope
        and verification.verification_status == "completed"
        and verification.verified_citation_count == summary["verified_citation_count"]
        and verification.missing_citation_count == summary["missing_citation_count"]
        and verification.invalid_citation_count == summary["invalid_citation_count"]
        and verification.verification_summary == summary
    )


def _citation_ids_from_context(ordered_citations: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("citation_id")) for item in ordered_citations if isinstance(item, dict) and item.get("citation_id")
    }


def _citation_ids_from_text(text: str | None) -> set[str]:
    return set(CITATION_PATTERN.findall(text or ""))


def _verify_citations(
    *, raw_output_text: str | None, prompt_citation_section: str, context_citations: list[dict[str, Any]]
) -> dict[str, Any]:
    evidence_ids = _citation_ids_from_context(context_citations)
    raw_reference_ids = _citation_ids_from_text(raw_output_text)
    prompt_reference_ids = _citation_ids_from_text(prompt_citation_section)
    referenced_ids = raw_reference_ids or prompt_reference_ids
    verified_ids = sorted(referenced_ids.intersection(evidence_ids))
    invalid_ids = sorted(referenced_ids.difference(evidence_ids))
    missing_ids = sorted(evidence_ids.difference(referenced_ids))
    return {
        "verification_algorithm": "deterministic_citation_id_match",
        "evidence_citation_ids": sorted(evidence_ids),
        "raw_reference_ids": sorted(raw_reference_ids),
        "prompt_reference_ids": sorted(prompt_reference_ids),
        "referenced_citation_ids": sorted(referenced_ids),
        "verified_citation_ids": verified_ids,
        "missing_citation_ids": missing_ids,
        "invalid_citation_ids": invalid_ids,
        "verified_citation_count": len(verified_ids),
        "missing_citation_count": len(missing_ids),
        "invalid_citation_count": len(invalid_ids),
        "evidence_exists": bool(evidence_ids),
        "reference_exists": bool(referenced_ids),
        "llm_used": False,
        "embeddings_used": False,
        "provider_called": False,
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
    }


def _assistant_runtime_evidence(
    db: Session,
    request_metadata: dict[str, Any] | None,
    organization_id: uuid.UUID | None,
):
    metadata = dict(request_metadata or {})
    raw_run_id = metadata.get("assistant_run_id")
    if raw_run_id is None:
        return None, None
    try:
        assistant_run_id = uuid.UUID(str(raw_run_id))
        if organization_id is None:
            raise ValueError("organization scope is required")
    except (TypeError, ValueError):
        return None, {
            "code": "assistant_execution_lineage_invalid",
            "severity": "blocking",
            "component": "assistant_citation_verification",
            "message": "Assistant execution lineage requires valid assistant_run_id and explicit organization scope.",
        }
    evidence = read_assistant_execution_evidence_v1(
        db,
        organization_id=organization_id,
        assistant_run_id=assistant_run_id,
    )
    if evidence is None:
        return None, {
            "code": "assistant_execution_evidence_missing",
            "severity": "blocking",
            "component": "assistant_citation_verification",
            "message": "Citation verification requires persisted organization-scoped assistant execution evidence.",
        }
    return evidence, None


def assistant_citation_verification_to_dict(record: AssistantCitationVerification) -> dict[str, Any]:
    return {
        "id": str(record.citation_verification_id),
        "citation_verification_id": str(record.citation_verification_id),
        "assistant_runtime_id": str(record.assistant_runtime_id) if record.assistant_runtime_id else None,
        "llm_execution_id": str(record.llm_execution_id),
        "prompt_package_id": str(record.prompt_package_id),
        "context_package_id": str(record.context_package_id),
        "verification_status": record.verification_status,
        "verified_citation_count": int(record.verified_citation_count or 0),
        "missing_citation_count": int(record.missing_citation_count or 0),
        "invalid_citation_count": int(record.invalid_citation_count or 0),
        "verification_summary": record.verification_summary or {},
        "runtime_metadata": record.runtime_metadata or {},
        "citation_runtime_created": True,
        "verification_completed": record.verification_status == "completed",
        "citation_verification_completed": record.verification_status == "completed",
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def build_assistant_citation_verification_runtime(
    db: Session,
    *,
    llm_execution_id: str,
    organization_id: uuid.UUID | None = None,
    request_metadata: dict[str, Any] | None = None,
    persist_snapshot: bool = True,
) -> dict[str, Any] | None:
    scoped_repository = AssistantRepository(db)
    try:
        artifact_uuid = uuid.UUID(str(llm_execution_id))
    except (TypeError, ValueError):
        return None
    scoped_artifact = scoped_repository.get_scoped_artifact(
        AssistantLlmExecution,
        AssistantLlmExecution.llm_execution_id,
        artifact_uuid,
        organization_id=organization_id,
        platform_scope=organization_id is None,
    )
    if scoped_artifact is None or (scoped_artifact.ownership_scope == "organization" and organization_id is None):
        return None
    gateway = build_assistant_citation_verification_gateway(
        db, llm_execution_id=llm_execution_id, request_metadata=request_metadata
    )
    if gateway.get("blocking_issues"):
        return {
            "assistant_citation_verification_schema_version": "1",
            "assistant_citation_verification_prepared": False,
            "assistant_citation_verification_gateway": gateway,
            "citation_runtime_created": False,
            "verification_completed": False,
            "verified_citation_count": 0,
            "missing_citation_count": 0,
            "invalid_citation_count": 0,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "postgresql_source_of_truth": True,
            "passed": False,
            "blocking_issues": gateway.get("blocking_issues") or [],
            "warnings": gateway.get("warnings") or [],
        }
    repository = AssistantRepository(db)
    llm_execution = scoped_artifact
    if llm_execution is None:
        return None
    prompt_package = repository.get_prompt_package(llm_execution.prompt_package_id)
    if prompt_package is None:
        return None
    context_package = repository.get_context_package(prompt_package.context_package_id)
    if context_package is None:
        return None
    assistant_execution, lineage_issue = _assistant_runtime_evidence(db, request_metadata, organization_id)
    if lineage_issue is not None:
        return {
            "assistant_citation_verification_schema_version": "1",
            "assistant_citation_verification_prepared": False,
            "assistant_citation_verification_gateway": gateway,
            "citation_runtime_created": False,
            "verification_completed": False,
            "verified_citation_count": 0,
            "missing_citation_count": 0,
            "invalid_citation_count": 0,
            "runtime_persistence": {"runtime_persistence": False, "persistence_completed": False},
            "postgresql_source_of_truth": True,
            "passed": False,
            "blocking_issues": [lineage_issue],
            "warnings": gateway.get("warnings") or [],
        }
    verification_summary = _verify_citations(
        raw_output_text=llm_execution.raw_output_text,
        prompt_citation_section=prompt_package.citation_section,
        context_citations=list(context_package.ordered_citations or []),
    )
    assistant_runtime_id = assistant_execution.assistant_run_id if assistant_execution is not None else None
    existing = repository.list_citation_verifications_by_llm_execution(llm_execution.llm_execution_id)
    if len(existing) > 1:
        return _citation_identity_conflict(llm_execution.llm_execution_id)
    created = not existing
    if existing:
        verification = existing[0]
    else:
        try:
            with db.begin_nested():
                verification = repository.create_citation_verification(
                    assistant_runtime_id=assistant_runtime_id,
                    llm_execution_id=llm_execution.llm_execution_id,
                    prompt_package_id=prompt_package.prompt_package_id,
                    context_package_id=context_package.context_package_id,
                    verification_status="completed",
                    verified_citation_count=int(verification_summary.get("verified_citation_count") or 0),
                    missing_citation_count=int(verification_summary.get("missing_citation_count") or 0),
                    invalid_citation_count=int(verification_summary.get("invalid_citation_count") or 0),
                    verification_summary=verification_summary,
                    runtime_metadata={
                        **dict(request_metadata or {}),
                        "assistant_citation_verification_prepared": True,
                        "citation_runtime_created": True,
                        "verification_completed": True,
                        "citation_verification_completed": True,
                        "postgresql_source_of_truth": True,
                    },
                )
        except IntegrityError as exc:
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != CITATION_IDENTITY_CONSTRAINT:
                raise
            winners = repository.list_citation_verifications_by_llm_execution(llm_execution.llm_execution_id)
            if len(winners) != 1:
                raise
            verification = winners[0]
            created = False
    if not _citation_matches_pipeline(
        verification,
        llm_execution,
        assistant_runtime_id=assistant_runtime_id,
        context_package_id=context_package.context_package_id,
        summary=verification_summary,
    ):
        return _citation_identity_conflict(llm_execution.llm_execution_id)
    repository.mark_llm_execution_citation_verified(llm_execution.llm_execution_id)
    db.commit()
    verification_dict = assistant_citation_verification_to_dict(verification)
    payload = {
        "assistant_citation_verification_schema_version": "1",
        "assistant_citation_verification_prepared": True,
        "assistant_citation_verification_gateway": gateway,
        "assistant_citation_verification": verification_dict,
        "id": str(verification.citation_verification_id),
        "citation_verification_id": str(verification.citation_verification_id),
        "assistant_runtime_id": str(assistant_runtime_id) if assistant_runtime_id else None,
        "llm_execution_id": str(llm_execution.llm_execution_id),
        "prompt_package_id": str(prompt_package.prompt_package_id),
        "context_package_id": str(context_package.context_package_id),
        "verification_status": "completed",
        "citation_runtime_created": created,
        "verification_completed": True,
        "citation_verification_completed": True,
        "verified_citation_count": int(verification.verified_citation_count or 0),
        "missing_citation_count": int(verification.missing_citation_count or 0),
        "invalid_citation_count": int(verification.invalid_citation_count or 0),
        "verification_summary": verification_summary,
        "final_response_created": False,
        "tool_called": False,
        "workflow_executed": False,
        "external_action_called": False,
        "autonomous_execution": False,
        "postgresql_source_of_truth": True,
        "passed": True,
        "blocking_issues": [],
        "warnings": gateway.get("warnings") or [],
    }
    if persist_snapshot:
        from app.services.runtime_persistence_runtime import persist_runtime_outputs

        payload["runtime_persistence"] = persist_runtime_outputs(
            db,
            execution_id=f"assistant-citation-verification:{verification.citation_verification_id}",
            artifact_id=None,
            runtime_outputs={"assistant_citation_verification": payload},
        )
        payload["runtime_persistence"] = {
            **payload["runtime_persistence"],
            "runtime_persistence": bool(payload["runtime_persistence"].get("persistence_completed")),
        }
    return payload


def read_assistant_citation_verification(db: Session, citation_verification_id: str) -> dict[str, Any] | None:
    try:
        verification_uuid = uuid.UUID(str(citation_verification_id))
    except (TypeError, ValueError):
        return None
    record = AssistantRepository(db).get_citation_verification(verification_uuid)
    return assistant_citation_verification_to_dict(record) if record is not None else None


__all__ = [
    "assistant_citation_verification_to_dict",
    "build_assistant_citation_verification_health",
    "build_assistant_citation_verification_runtime",
    "read_assistant_citation_verification",
]
