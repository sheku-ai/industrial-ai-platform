from __future__ import annotations

from typing import Any

from app.services.product_acceptance.evidence_runtime import EvidenceAwareLocalProductAcceptanceRuntime
from app.services.product_acceptance.idempotency import build_idempotency_report, idempotency_gate_results
from app.services.product_acceptance.identity import idempotency_key
from app.services.product_acceptance.runtime import SCENARIO, _nested_get


class IdempotencyEvidenceAwareLocalProductAcceptanceRuntime(EvidenceAwareLocalProductAcceptanceRuntime):
    """Product Acceptance runtime with persisted-evidence idempotency verification."""

    def _conversation(self, phase: str) -> None:
        assistant_id = self._resource_id("assistant")
        organization_id = self._resource_id("organization")
        if not assistant_id or not organization_id:
            self._functional_failure(phase, "assistant_required", {})
            return

        request_id = self._chat_request_id(assistant_id)
        payload = self._chat_payload(assistant_id, organization_id, request_id)
        result = self.http.post("/assistants/chat", payload)
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
                    "request_id": request_id,
                },
            )

        persisted_evidence, evidence_result = self._assistant_conversation_evidence(
            result_ok=result.ok,
            conversation_id=conversation_id,
            assistant_run_id=assistant_run_id,
            assistant_id=assistant_id,
            assistant_response_id=assistant_response_id,
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

        if conversation_id and self.state.resources.get("conversation") is not None:
            self.state.resources["conversation"]["assistant_conversation_evidence"] = persisted_evidence

        details: dict[str, Any] = {
            "functional_response": data,
            "functional_chat_succeeded": bool(result.ok and conversation_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "assistant_run_id": str(assistant_run_id) if assistant_run_id else None,
            "assistant_response_id": str(assistant_response_id) if assistant_response_id else None,
            "request_id": request_id,
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

    def _idempotency(self, phase: str) -> None:
        counts_before = self._inventory_counts()
        resources_before = dict(self.state.resources)
        document_evidence_before = self._fetch_document_evidence()
        conversation_before = resources_before.get("conversation") or {}

        resources_after = self._read_after_write_resources(resources_before)
        assistant_replay = self._replay_chat(conversation_before)
        document_evidence_after = self._fetch_document_evidence()
        counts_after = self._inventory_counts()

        report = build_idempotency_report(resources_before, resources_after, counts_before, counts_after)
        report["evidence_idempotency"] = {
            "processing": self._processing_idempotency_details(document_evidence_before, document_evidence_after),
            "knowledge": self._knowledge_idempotency_details(document_evidence_before, document_evidence_after),
            "assistant_response": assistant_replay,
        }
        self.state.idempotency = report

        replaced = {"processing_idempotent", "knowledge_idempotent", "assistant_response_idempotent"}
        for gate in idempotency_gate_results(report):
            if gate["gate_code"] in replaced:
                continue
            self._gate(
                phase,
                gate["gate_code"],
                gate["status"],
                gate.get("details", {}),
                error_code=gate.get("error_code"),
                error_message=gate.get("error_message"),
            )

        processing = report["evidence_idempotency"]["processing"]
        self._gate(
            phase,
            "processing_idempotent",
            "PASSED" if processing["idempotent"] else "FAILED",
            processing,
            error_code=None if processing["idempotent"] else "IDEMPOTENCY_VIOLATION",
        )

        knowledge = report["evidence_idempotency"]["knowledge"]
        self._gate(
            phase,
            "knowledge_idempotent",
            "PASSED" if knowledge["idempotent"] else "FAILED",
            knowledge,
            error_code=None if knowledge["idempotent"] else "IDEMPOTENCY_VIOLATION",
        )

        assistant = report["evidence_idempotency"]["assistant_response"]
        self._gate(
            phase,
            "assistant_response_idempotent",
            "PASSED" if assistant["idempotent"] else "FAILED",
            assistant,
            error_code=None if assistant["idempotent"] else "IDEMPOTENCY_VIOLATION",
        )

    def _fetch_document_evidence(self) -> dict[str, Any]:
        artifact_id = self._resource_id("artifact")
        if not artifact_id:
            return {}
        result = self.http.get(
            "/product-acceptance/runtime-evidence/document-lifecycle",
            query={"artifact_id": artifact_id},
        )
        return result.data if result.ok and isinstance(result.data, dict) else {}

    @staticmethod
    def _processing_idempotency_details(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_processing = before.get("processing") if isinstance(before.get("processing"), dict) else {}
        after_processing = after.get("processing") if isinstance(after.get("processing"), dict) else {}
        before_id = before_processing.get("processing_evidence_id")
        after_id = after_processing.get("processing_evidence_id")
        lineage_fields = ("organization_id", "artifact_id", "document_record_id", "document_version_id")
        lineage_matches = all(str(before.get(key) or "") == str(after.get(key) or "") for key in lineage_fields)
        idempotent = bool(
            before.get("authority") == "postgresql"
            and after.get("authority") == "postgresql"
            and before_processing.get("ready") is True
            and after_processing.get("ready") is True
            and before_processing.get("contract") == "ProcessingEvidenceV1"
            and after_processing.get("contract") == "ProcessingEvidenceV1"
            and before_id
            and before_id == after_id
            and lineage_matches
        )
        return {
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "processing_evidence_id_before": before_id,
            "processing_evidence_id_after": after_id,
            "same_persisted_evidence_reused": bool(before_id and before_id == after_id),
            "lineage_matches": lineage_matches,
            "idempotent": idempotent,
        }

    @staticmethod
    def _knowledge_idempotency_details(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_publication = (
            before.get("knowledge_publication") if isinstance(before.get("knowledge_publication"), dict) else {}
        )
        after_publication = (
            after.get("knowledge_publication") if isinstance(after.get("knowledge_publication"), dict) else {}
        )
        before_publication_evidence = (
            before_publication.get("evidence") if isinstance(before_publication.get("evidence"), dict) else {}
        )
        after_publication_evidence = (
            after_publication.get("evidence") if isinstance(after_publication.get("evidence"), dict) else {}
        )
        before_index = before.get("knowledge_index") if isinstance(before.get("knowledge_index"), dict) else {}
        after_index = after.get("knowledge_index") if isinstance(after.get("knowledge_index"), dict) else {}
        before_index_evidence = before_index.get("evidence") if isinstance(before_index.get("evidence"), dict) else {}
        after_index_evidence = after_index.get("evidence") if isinstance(after_index.get("evidence"), dict) else {}

        publication_before = before_publication_evidence.get("evidence_id")
        publication_after = after_publication_evidence.get("evidence_id")
        document_before = before_index_evidence.get("knowledge_document_id")
        document_after = after_index_evidence.get("knowledge_document_id")
        publication_identity_reused = bool(publication_before and publication_before == publication_after)
        index_identity_reused = bool(document_before and document_before == document_after)
        idempotent = bool(
            before_publication.get("ready") is True
            and after_publication.get("ready") is True
            and before_index.get("ready") is True
            and after_index.get("ready") is True
            and before_publication_evidence.get("contract") == "KnowledgePublicationEvidenceV1"
            and after_publication_evidence.get("contract") == "KnowledgePublicationEvidenceV1"
            and before_index_evidence.get("contract") == "KnowledgeIndexEvidenceV1"
            and after_index_evidence.get("contract") == "KnowledgeIndexEvidenceV1"
            and publication_identity_reused
            and index_identity_reused
            and before_index_evidence.get("publication_id") == after_index_evidence.get("publication_id")
        )
        return {
            "authority": "postgresql",
            "publication_contract": "KnowledgePublicationEvidenceV1",
            "index_contract": "KnowledgeIndexEvidenceV1",
            "publication_evidence_id_before": publication_before,
            "publication_evidence_id_after": publication_after,
            "knowledge_document_id_before": document_before,
            "knowledge_document_id_after": document_after,
            "same_publication_evidence_reused": publication_identity_reused,
            "same_knowledge_document_reused": index_identity_reused,
            "idempotent": idempotent,
        }

    def _replay_chat(self, conversation_before: dict[str, Any]) -> dict[str, Any]:
        assistant_id = self._resource_id("assistant")
        organization_id = self._resource_id("organization")
        request_id = str(conversation_before.get("request_id") or "")
        expected_conversation_id = str(conversation_before.get("conversation_id") or "")
        expected_run_id = str(conversation_before.get("assistant_run_id") or "")
        expected_response_id = str(conversation_before.get("assistant_response_id") or "")
        initial_evidence = (
            conversation_before.get("assistant_conversation_evidence")
            if isinstance(conversation_before.get("assistant_conversation_evidence"), dict)
            else {}
        )
        initial_event = (
            initial_evidence.get("conversation_event")
            if isinstance(initial_evidence.get("conversation_event"), dict)
            else {}
        )

        if not assistant_id or not organization_id or not request_id:
            return {
                "authority": "postgresql",
                "request_id": request_id or None,
                "idempotent": False,
                "reason": "assistant_idempotency_prerequisite_missing",
            }

        result = self.http.post("/assistants/chat", self._chat_payload(assistant_id, organization_id, request_id))
        data = result.data if isinstance(result.data, dict) else {}
        conversation_id = str(
            _nested_get(data, "conversation_id") or _nested_get(data, "conversation.conversation_id") or ""
        )
        response_run_id = str(
            _nested_get(data, "assistant_run_id")
            or _nested_get(data, "runtime_chain.assistant_runtime.assistant_run_id")
            or ""
        )
        response_id = str(
            _nested_get(data, "assistant_response_id")
            or _nested_get(data, "assistant_response.assistant_response_id")
            or ""
        )
        evidence_run_id = response_run_id or expected_run_id
        evidence_response_id = response_id or expected_response_id
        persisted_evidence, evidence_result = self._assistant_conversation_evidence(
            result_ok=result.ok,
            conversation_id=conversation_id or expected_conversation_id or None,
            assistant_run_id=evidence_run_id or None,
            assistant_id=assistant_id,
            assistant_response_id=evidence_response_id or None,
        )
        replay_event = (
            persisted_evidence.get("conversation_event")
            if isinstance(persisted_evidence.get("conversation_event"), dict)
            else {}
        )
        persisted_run_id = str(persisted_evidence.get("assistant_run_id") or "")
        replay_run_id = response_run_id or persisted_run_id
        replay_response_id = response_id or str(replay_event.get("assistant_response_id") or "")
        same_event = bool(
            initial_event.get("conversation_turn_id")
            and initial_event.get("conversation_turn_id") == replay_event.get("conversation_turn_id")
        )
        same_response = bool(
            not expected_response_id
            or (replay_response_id and replay_response_id == expected_response_id)
        )
        idempotent = bool(
            result.ok
            and data.get("idempotent_replay") is True
            and expected_conversation_id
            and conversation_id == expected_conversation_id
            and expected_run_id
            and replay_run_id == expected_run_id
            and same_event
            and same_response
            and persisted_evidence.get("ready") is True
        )
        details: dict[str, Any] = {
            "authority": "postgresql",
            "request_id": request_id,
            "functional_replay_succeeded": result.ok,
            "idempotent_replay": data.get("idempotent_replay") is True,
            "conversation_id_before": expected_conversation_id or None,
            "conversation_id_after": conversation_id or None,
            "assistant_run_id_before": expected_run_id or None,
            "assistant_run_id_after": replay_run_id or None,
            "assistant_response_id_before": expected_response_id or None,
            "assistant_response_id_after": replay_response_id or None,
            "conversation_turn_id_before": initial_event.get("conversation_turn_id"),
            "conversation_turn_id_after": replay_event.get("conversation_turn_id"),
            "same_conversation_reused": bool(expected_conversation_id and conversation_id == expected_conversation_id),
            "same_assistant_run_reused": bool(expected_run_id and replay_run_id == expected_run_id),
            "same_conversation_event_reused": same_event,
            "same_assistant_response_reused": same_response,
            "persisted_evidence": persisted_evidence,
            "idempotent": idempotent,
        }
        if evidence_result is not None and not evidence_result.ok:
            details["evidence_status_code"] = evidence_result.status_code
            details["evidence_error"] = evidence_result.error
        return details

    def _assistant_conversation_evidence(
        self,
        *,
        result_ok: bool,
        conversation_id: Any,
        assistant_run_id: Any,
        assistant_id: str,
        assistant_response_id: Any,
    ) -> tuple[dict[str, Any], Any]:
        evidence_result = None
        if result_ok and conversation_id and assistant_run_id:
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
        return persisted_evidence, evidence_result

    def _chat_request_id(self, assistant_id: str) -> str:
        return idempotency_key(self.identity.execution_key, "conversation", "chat", assistant_id)

    def _chat_payload(self, assistant_id: str, organization_id: str, request_id: str) -> dict[str, Any]:
        return {
            "assistant_id": assistant_id,
            "message": "What is the inspection interval and governing reference code?",
            "request_id": request_id,
            "requested_by": "local-product-acceptance",
            "runtime_context": {"organization_id": organization_id},
            "runtime_metadata": {
                "organization_id": organization_id,
                "scenario": SCENARIO,
                "execution_key": self.identity.execution_key,
            },
        }
