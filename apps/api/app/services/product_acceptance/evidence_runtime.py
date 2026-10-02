from __future__ import annotations

from typing import Any

from app.services.product_acceptance.runtime import (
    ACCEPTANCE_SEARCH_QUERY,
    SCENARIO,
    LocalProductAcceptanceRuntime,
    _nested_get,
)


class EvidenceAwareLocalProductAcceptanceRuntime(LocalProductAcceptanceRuntime):
    """Product Acceptance runtime that observes authoritative persisted evidence."""

    def _document_lifecycle_assertions(self, phase: str) -> None:
        if phase == "binary_upload":
            super()._document_lifecycle_assertions(phase)
            return
        if phase not in {"processing", "chunking", "knowledge_publication"}:
            super()._document_lifecycle_assertions(phase)
            return

        evidence = self._read_document_runtime_evidence(phase)
        if evidence is None:
            return
        lifecycle = self.state.resources.get("document_lifecycle") or {}
        section = evidence.get(phase)
        section_payload = section if isinstance(section, dict) else {}
        lineage_matches = self._document_evidence_lineage_matches(evidence)
        contract_matches = self._section_contract_matches(phase, section_payload)
        passed = bool(section_payload.get("ready") is True and lineage_matches and contract_matches)
        details: dict[str, Any] = {
            "authority": evidence.get("authority"),
            "runtime_evidence_schema_version": evidence.get("runtime_evidence_schema_version"),
            "organization_id": evidence.get("organization_id"),
            "artifact_id": evidence.get("artifact_id"),
            "document_record_id": evidence.get("document_record_id"),
            "document_version_id": evidence.get("document_version_id"),
            "lineage_matches": lineage_matches,
            "contract_matches": contract_matches,
            "evidence": section_payload,
            "legacy_lifecycle_signal": self._legacy_lifecycle_signal(phase, lifecycle),
        }
        self._gate(
            phase,
            f"{phase}_ready",
            "PASSED" if passed else "FAILED",
            details,
            error_code=None if passed else self._phase_error_code(phase),
        )

    def _knowledge_index(self, phase: str) -> None:
        evidence = self._read_document_runtime_evidence(phase)
        if evidence is None:
            return
        lifecycle = self.state.resources.get("document_lifecycle") or {}
        section = evidence.get("knowledge_index")
        section_payload = section if isinstance(section, dict) else {}
        index_evidence = section_payload.get("evidence")
        index_payload = index_evidence if isinstance(index_evidence, dict) else {}
        lineage_matches = self._document_evidence_lineage_matches(evidence)
        contract_matches = bool(
            section_payload.get("authority") == "postgresql"
            and section_payload.get("contract") == "KnowledgeIndexEvidenceV1"
            and section_payload.get("knowledge_document_id")
            and index_payload.get("contract") == "KnowledgeIndexEvidenceV1"
            and index_payload.get("knowledge_document_id") == section_payload.get("knowledge_document_id")
            and index_payload.get("status") == "indexed"
        )
        passed = bool(section_payload.get("ready") is True and lineage_matches and contract_matches)
        self._gate(
            phase,
            "knowledge_index_ready",
            "PASSED" if passed else "FAILED",
            {
                "authority": evidence.get("authority"),
                "runtime_evidence_schema_version": evidence.get("runtime_evidence_schema_version"),
                "organization_id": evidence.get("organization_id"),
                "artifact_id": evidence.get("artifact_id"),
                "document_record_id": evidence.get("document_record_id"),
                "document_version_id": evidence.get("document_version_id"),
                "lineage_matches": lineage_matches,
                "contract_matches": contract_matches,
                "evidence": section_payload,
                "legacy_lifecycle_signal": {
                    "flag": "knowledge_indexed",
                    "value": _nested_get(lifecycle, "knowledge_indexed"),
                    "knowledge_records": _nested_get(lifecycle, "knowledge_records", default=0),
                    "authoritative": False,
                },
            },
            error_code=None if passed else "KNOWLEDGE_INDEX_NOT_COMPLETED",
        )

    def _enterprise_search(self, phase: str) -> None:
        document_evidence = self._read_document_runtime_evidence(phase)
        if document_evidence is None:
            return
        knowledge_index = document_evidence.get("knowledge_index")
        knowledge_index_payload = knowledge_index if isinstance(knowledge_index, dict) else {}
        index_evidence = knowledge_index_payload.get("evidence")
        index_payload = index_evidence if isinstance(index_evidence, dict) else {}
        artifact_id = str(document_evidence.get("artifact_id") or "")
        knowledge_document_id = str(index_payload.get("knowledge_document_id") or "")
        organization_id = self._resource_id("organization")

        if (
            not organization_id
            or not artifact_id
            or not knowledge_document_id
            or not knowledge_index_payload.get("ready")
        ):
            self._gate(
                phase,
                "enterprise_search_query",
                "FAILED",
                {
                    "authority": "postgresql",
                    "organization_id": organization_id,
                    "artifact_id": artifact_id,
                    "knowledge_document_id": knowledge_document_id,
                    "knowledge_index_evidence": knowledge_index_payload,
                },
                error_code="RESOURCE_LINEAGE_INCOMPLETE",
            )
            return

        result = self.http.post(
            "/enterprise-search/search",
            {
                "organization_id": organization_id,
                "query": ACCEPTANCE_SEARCH_QUERY,
                "top_k": 5,
                "include_debug": True,
                "artifact_id": artifact_id,
                "knowledge_document_id": knowledge_document_id,
            },
        )
        data = result.data if isinstance(result.data, dict) else {}
        results = _nested_get(data, "results", default=[]) or _nested_get(data, "items", default=[]) or []
        evidence_id = _runtime_persistence_evidence_id(
            data,
            runtime_domain="enterprise_search",
            record_type="search_result_set",
        )
        evidence_result = (
            self.http.get(
                "/product-acceptance/runtime-evidence/enterprise-search",
                query={
                    "evidence_id": evidence_id,
                    "expected_query": ACCEPTANCE_SEARCH_QUERY,
                    "expected_artifact_id": artifact_id,
                    "expected_knowledge_document_id": knowledge_document_id,
                },
            )
            if evidence_id
            else None
        )
        persisted_evidence = (
            evidence_result.data
            if evidence_result is not None and evidence_result.ok and isinstance(evidence_result.data, dict)
            else {}
        )
        evidence_payload = persisted_evidence.get("evidence")
        enterprise_search_evidence = evidence_payload if isinstance(evidence_payload, dict) else {}
        contract_matches = bool(
            persisted_evidence.get("authority") == "postgresql"
            and persisted_evidence.get("ready") is True
            and enterprise_search_evidence.get("contract") == "EnterpriseSearchEvidenceV1"
            and enterprise_search_evidence.get("evidence_id") == evidence_id
            and enterprise_search_evidence.get("organization_id") == organization_id
            and enterprise_search_evidence.get("query") == ACCEPTANCE_SEARCH_QUERY
            and enterprise_search_evidence.get("search_status") == "completed"
            and _positive_int(enterprise_search_evidence.get("result_count")) >= 1
            and enterprise_search_evidence.get("search_uses_postgresql") is True
            and enterprise_search_evidence.get("search_uses_postgresql_fts") is True
            and enterprise_search_evidence.get("semantic_search_used") is False
            and enterprise_search_evidence.get("embeddings_required") is False
            and enterprise_search_evidence.get("ai_required") is False
            and enterprise_search_evidence.get("persistence_status") == "persisted"
        )
        passed = bool(result.ok and results and evidence_id and contract_matches)
        details = {
            "functional_response": data,
            "functional_search_succeeded": bool(result.ok and results),
            "authority": persisted_evidence.get("authority") or "postgresql",
            "evidence_id": evidence_id,
            "contract_matches": contract_matches,
            "persisted_evidence": persisted_evidence,
            "knowledge_index_evidence": knowledge_index_payload,
            "legacy_functional_result_authoritative": False,
        }
        if evidence_result is not None and not evidence_result.ok:
            details["evidence_status_code"] = evidence_result.status_code
            details["evidence_error"] = evidence_result.error
            details["evidence_response"] = evidence_result.data
        self._gate(
            phase,
            "enterprise_search_query",
            "PASSED" if passed else "FAILED",
            details,
            error_code=None if passed else "RESOURCE_LINEAGE_INCOMPLETE",
        )

    def _conversation(self, phase: str) -> None:
        assistant_id = self._resource_id("assistant")
        organization_id = self._resource_id("organization")
        if not assistant_id or not organization_id:
            self._functional_failure(phase, "assistant_required", {})
            return

        result = self.http.post(
            "/assistants/chat",
            {
                "assistant_id": assistant_id,
                "message": "What is the inspection interval and governing reference code?",
                "requested_by": "local-product-acceptance",
                "runtime_context": {"organization_id": organization_id},
                "runtime_metadata": {
                    "organization_id": organization_id,
                    "scenario": SCENARIO,
                    "execution_key": self.identity.execution_key,
                },
            },
        )
        data = result.data if isinstance(result.data, dict) else {}
        conversation_id = _nested_get(data, "conversation_id") or _nested_get(data, "conversation.conversation_id")
        assistant_run_id = _nested_get(data, "assistant_run_id") or _nested_get(
            data, "runtime_chain.assistant_runtime.assistant_run_id"
        )
        assistant_response_id = _nested_get(data, "assistant_response_id") or _nested_get(
            data, "assistant_response.assistant_response_id"
        )

        if conversation_id:
            self._resource(
                "conversation",
                str(assistant_response_id or conversation_id),
                f"conversation:{self.identity.execution_key}",
                True,
                False,
                {
                    **data,
                    "conversation_id": str(conversation_id),
                    "assistant_run_id": str(assistant_run_id) if assistant_run_id else None,
                    "assistant_response_id": str(assistant_response_id) if assistant_response_id else None,
                },
            )

        evidence_result = None
        if result.ok and conversation_id and assistant_run_id:
            query = {
                "conversation_id": str(conversation_id),
                "assistant_run_id": str(assistant_run_id),
                "expected_assistant_id": str(assistant_id),
            }
            if assistant_response_id:
                query["expected_assistant_response_id"] = str(assistant_response_id)
            evidence_result = self.http.get(
                "/product-acceptance/runtime-evidence/assistant-conversation",
                query=query,
            )

        persisted_evidence = (
            evidence_result.data
            if evidence_result is not None and evidence_result.ok and isinstance(evidence_result.data, dict)
            else {}
        )
        assistant_execution = persisted_evidence.get("assistant_execution")
        assistant_execution_payload = assistant_execution if isinstance(assistant_execution, dict) else {}
        conversation_event = persisted_evidence.get("conversation_event")
        conversation_event_payload = conversation_event if isinstance(conversation_event, dict) else {}
        contract_matches = bool(
            persisted_evidence.get("authority") == "postgresql"
            and persisted_evidence.get("ready") is True
            and persisted_evidence.get("organization_id") == organization_id
            and persisted_evidence.get("conversation_id") == str(conversation_id or "")
            and persisted_evidence.get("assistant_run_id") == str(assistant_run_id or "")
            and assistant_execution_payload.get("contract") == "AssistantExecutionEvidenceV1"
            and assistant_execution_payload.get("assistant_run_id") == str(assistant_run_id or "")
            and assistant_execution_payload.get("assistant_id") == assistant_id
            and assistant_execution_payload.get("authority") == "postgresql"
            and conversation_event_payload.get("contract") == "ConversationEventEvidenceV1"
            and conversation_event_payload.get("conversation_id") == str(conversation_id or "")
            and conversation_event_payload.get("assistant_run_id") == str(assistant_run_id or "")
            and conversation_event_payload.get("assistant_id") == assistant_id
            and conversation_event_payload.get("turn_role") == "assistant"
            and conversation_event_payload.get("turn_status") == "completed"
            and conversation_event_payload.get("output_present") is True
            and (
                not assistant_response_id
                or conversation_event_payload.get("assistant_response_id") == str(assistant_response_id)
            )
        )
        passed = bool(result.ok and conversation_id and assistant_run_id and contract_matches)
        details: dict[str, Any] = {
            "functional_response": data,
            "functional_chat_succeeded": bool(result.ok and conversation_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "assistant_run_id": str(assistant_run_id) if assistant_run_id else None,
            "assistant_response_id": str(assistant_response_id) if assistant_response_id else None,
            "authority": persisted_evidence.get("authority") or "postgresql",
            "contract_matches": contract_matches,
            "persisted_evidence": persisted_evidence,
            "legacy_functional_result_authoritative": False,
        }
        if evidence_result is not None and not evidence_result.ok:
            details["evidence_status_code"] = evidence_result.status_code
            details["evidence_error"] = evidence_result.error
            details["evidence_response"] = evidence_result.data
        self._gate(
            phase,
            "conversation_turn_created",
            "PASSED" if passed else "FAILED",
            details,
            error_code=None if passed else "RESOURCE_LINEAGE_INCOMPLETE",
        )

    def _read_document_runtime_evidence(self, phase: str) -> dict[str, Any] | None:
        lifecycle = self.state.resources.get("document_lifecycle") or {}
        artifact_id = _nested_get(lifecycle, "artifact_id") or self._resource_id("artifact")
        organization_id = self._resource_id("organization")
        document_record_id = _nested_get(lifecycle, "document_record_id") or self._resource_id("document_record")
        document_version_id = _nested_get(lifecycle, "document_version_id") or self._resource_id("document_version")

        if not artifact_id or not organization_id:
            gate = "enterprise_search_query" if phase == "enterprise_search" else f"{phase}_ready"
            self._gate(
                phase,
                gate,
                "FAILED",
                {
                    "authority": "postgresql",
                    "artifact_id": artifact_id,
                    "organization_id": organization_id,
                    "document_record_id": document_record_id,
                    "document_version_id": document_version_id,
                    "functional_error": "RESOURCE_LINEAGE_INCOMPLETE",
                },
                error_code="RESOURCE_LINEAGE_INCOMPLETE",
            )
            return None

        result = self.http.get(
            "/product-acceptance/runtime-evidence/document-lifecycle",
            query={"artifact_id": artifact_id},
        )
        if not result.ok or not isinstance(result.data, dict):
            gate = "enterprise_search_query" if phase == "enterprise_search" else f"{phase}_ready"
            phase_error = (
                "RESOURCE_LINEAGE_INCOMPLETE" if phase == "enterprise_search" else self._phase_error_code(phase)
            )
            self._gate(
                phase,
                gate,
                "BLOCKED_BY_ENVIRONMENT" if result.status_code == 0 else "FAILED",
                {
                    "authority": "postgresql",
                    "artifact_id": artifact_id,
                    "organization_id": organization_id,
                    "document_record_id": document_record_id,
                    "document_version_id": document_version_id,
                    "status_code": result.status_code,
                    "response": result.data,
                    "error": result.error,
                },
                error_code="REQUIRED_RUNTIME_NOT_AVAILABLE" if result.status_code == 0 else phase_error,
            )
            return None
        return result.data

    def _document_evidence_lineage_matches(self, evidence: dict[str, Any]) -> bool:
        lifecycle = self.state.resources.get("document_lifecycle") or {}
        artifact_id = _nested_get(lifecycle, "artifact_id") or self._resource_id("artifact")
        organization_id = self._resource_id("organization")
        document_record_id = _nested_get(lifecycle, "document_record_id") or self._resource_id("document_record")
        document_version_id = _nested_get(lifecycle, "document_version_id") or self._resource_id("document_version")
        return bool(
            evidence.get("authority") == "postgresql"
            and str(evidence.get("organization_id") or "") == str(organization_id)
            and str(evidence.get("artifact_id") or "") == str(artifact_id)
            and str(evidence.get("document_record_id") or "") == str(document_record_id)
            and str(evidence.get("document_version_id") or "") == str(document_version_id)
        )

    @staticmethod
    def _section_contract_matches(phase: str, section: dict[str, Any]) -> bool:
        if phase == "processing":
            return bool(
                section.get("authority") == "postgresql"
                and section.get("contract") == "ProcessingEvidenceV1"
                and section.get("processing_evidence_id")
            )
        if phase == "chunking":
            chunk_count = _positive_int(section.get("chunk_count"))
            return bool(
                section.get("authority") == "postgresql"
                and section.get("contract") == "ProcessingEvidenceV1"
                and section.get("processing_evidence_id")
                and chunk_count >= 1
            )
        publication = section.get("evidence")
        publication_payload = publication if isinstance(publication, dict) else {}
        return bool(
            section.get("authority") == "postgresql"
            and publication_payload.get("contract") == "KnowledgePublicationEvidenceV1"
            and publication_payload.get("evidence_id")
            and publication_payload.get("record_persistence_status") == "persisted"
            and publication_payload.get("publication_status") == "completed"
            and publication_payload.get("publication_completed") is True
            and publication_payload.get("publication_succeeded") is True
            and publication_payload.get("knowledge_published") is True
            and _positive_int(publication_payload.get("published_chunk_count")) >= 1
        )

    @staticmethod
    def _legacy_lifecycle_signal(phase: str, lifecycle: dict[str, Any]) -> dict[str, Any]:
        key_by_phase = {
            "processing": "processing_ready",
            "chunking": "chunks_created",
            "knowledge_publication": "knowledge_published",
        }
        key = key_by_phase[phase]
        return {"flag": key, "value": _nested_get(lifecycle, key), "authoritative": False}

    @staticmethod
    def _phase_error_code(phase: str) -> str:
        return {
            "processing": "RESOURCE_LINEAGE_INCOMPLETE",
            "chunking": "CHUNK_PERSISTENCE_NOT_COMPLETED",
            "knowledge_publication": "KNOWLEDGE_PUBLICATION_NOT_COMPLETED",
            "knowledge_index": "KNOWLEDGE_INDEX_NOT_COMPLETED",
        }[phase]


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _runtime_persistence_evidence_id(
    payload: dict[str, Any],
    *,
    runtime_domain: str,
    record_type: str,
) -> str | None:
    persistence = payload.get("runtime_persistence")
    persistence_payload = persistence if isinstance(persistence, dict) else {}
    records = persistence_payload.get("persisted_records")
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        if (
            record.get("runtime_domain") == runtime_domain
            and record.get("record_type") == record_type
            and record.get("persistence_status") == "persisted"
            and record.get("id")
        ):
            return str(record["id"])
    return None
