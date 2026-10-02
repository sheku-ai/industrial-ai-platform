from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.evidence_runtime import (  # noqa: E402
    EvidenceAwareLocalProductAcceptanceRuntime,
)
from app.services.product_acceptance.gateway import HttpResult  # noqa: E402
from app.services.product_acceptance.runtime import RuntimeOptions  # noqa: E402

ORG_ID = "11111111-1111-1111-1111-111111111111"
ARTIFACT_ID = "22222222-2222-2222-2222-222222222222"
DOCUMENT_ID = "33333333-3333-3333-3333-333333333333"
VERSION_ID = "44444444-4444-4444-4444-444444444444"
PROCESSING_EVIDENCE_ID = "55555555-5555-5555-5555-555555555555"
PUBLICATION_EVIDENCE_ID = "66666666-6666-6666-6666-666666666666"


def _runtime() -> EvidenceAwareLocalProductAcceptanceRuntime:
    runtime = EvidenceAwareLocalProductAcceptanceRuntime(RuntimeOptions(api_base_url="http://127.0.0.1:8000/api"))
    runtime.state.resources.update(
        {
            "organization": {"id": ORG_ID},
            "artifact": {"id": ARTIFACT_ID},
            "document_record": {"id": DOCUMENT_ID},
            "document_version": {"id": VERSION_ID},
            "document_lifecycle": {
                "artifact_id": ARTIFACT_ID,
                "document_record_id": DOCUMENT_ID,
                "document_version_id": VERSION_ID,
                "processing_ready": True,
                "chunks_created": True,
                "knowledge_published": True,
            },
        }
    )
    return runtime


def _authoritative_payload() -> dict:
    return {
        "runtime_evidence_schema_version": "1",
        "authority": "postgresql",
        "organization_id": ORG_ID,
        "artifact_id": ARTIFACT_ID,
        "document_record_id": DOCUMENT_ID,
        "document_version_id": VERSION_ID,
        "processing": {
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "processing_evidence_id": PROCESSING_EVIDENCE_ID,
            "processing_status": "completed",
            "processing_chunk_count": 2,
            "ready": True,
            "blocking_issues": [],
        },
        "chunking": {
            "authority": "postgresql",
            "contract": "ProcessingEvidenceV1",
            "processing_evidence_id": PROCESSING_EVIDENCE_ID,
            "chunk_count": 2,
            "ready": True,
            "blocking_issues": [],
        },
        "knowledge_publication": {
            "authority": "postgresql",
            "ready": True,
            "blocking_issues": [],
            "evidence": {
                "contract": "KnowledgePublicationEvidenceV1",
                "contract_version": "v1",
                "evidence_id": PUBLICATION_EVIDENCE_ID,
                "organization_id": ORG_ID,
                "artifact_id": ARTIFACT_ID,
                "publication_status": "completed",
                "publication_completed": True,
                "publication_succeeded": True,
                "knowledge_published": True,
                "published_chunk_count": 2,
                "record_persistence_status": "persisted",
            },
        },
    }


def _serve(runtime: EvidenceAwareLocalProductAcceptanceRuntime, payload: dict) -> None:
    runtime.http.get = MagicMock(
        return_value=HttpResult(
            ok=True,
            status_code=200,
            method="GET",
            path="/product-acceptance/runtime-evidence/document-lifecycle",
            data=payload,
        )
    )


def test_processing_ready_requires_authoritative_processing_evidence() -> None:
    runtime = _runtime()
    _serve(runtime, _authoritative_payload())

    runtime._document_lifecycle_assertions("processing")

    gate = runtime.state.gates[-1]
    assert gate["gate_code"] == "processing_ready"
    assert gate["status"] == "PASSED"
    assert gate["details"]["authority"] == "postgresql"
    assert gate["details"]["contract_matches"] is True
    assert gate["details"]["legacy_lifecycle_signal"] == {
        "flag": "processing_ready",
        "value": True,
        "authoritative": False,
    }


def test_processing_legacy_true_without_persisted_evidence_fails() -> None:
    runtime = _runtime()
    payload = _authoritative_payload()
    payload["processing"] = {
        "authority": "postgresql",
        "contract": "ProcessingEvidenceV1",
        "processing_evidence_id": None,
        "ready": False,
        "blocking_issues": [{"code": "processing_evidence_missing"}],
    }
    _serve(runtime, payload)

    runtime._document_lifecycle_assertions("processing")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "RESOURCE_LINEAGE_INCOMPLETE"
    assert gate["details"]["legacy_lifecycle_signal"]["value"] is True
    assert gate["details"]["legacy_lifecycle_signal"]["authoritative"] is False


def test_chunking_requires_persisted_processing_chunk_count() -> None:
    runtime = _runtime()
    payload = _authoritative_payload()
    payload["chunking"] = {
        "authority": "postgresql",
        "contract": "ProcessingEvidenceV1",
        "processing_evidence_id": PROCESSING_EVIDENCE_ID,
        "chunk_count": 0,
        "ready": False,
        "blocking_issues": [{"code": "processing_chunk_count_empty"}],
    }
    _serve(runtime, payload)

    runtime._document_lifecycle_assertions("chunking")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "CHUNK_PERSISTENCE_NOT_COMPLETED"
    assert gate["details"]["legacy_lifecycle_signal"]["value"] is True


def test_knowledge_publication_legacy_true_without_persisted_evidence_fails() -> None:
    runtime = _runtime()
    payload = _authoritative_payload()
    payload["knowledge_publication"] = {
        "authority": "postgresql",
        "ready": False,
        "evidence": None,
        "blocking_issues": [{"code": "knowledge_publication_evidence_missing"}],
    }
    _serve(runtime, payload)

    runtime._document_lifecycle_assertions("knowledge_publication")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["error_code"] == "KNOWLEDGE_PUBLICATION_NOT_COMPLETED"
    assert gate["details"]["legacy_lifecycle_signal"]["value"] is True


def test_authoritative_evidence_with_wrong_document_lineage_fails() -> None:
    runtime = _runtime()
    payload = _authoritative_payload()
    payload["document_version_id"] = "77777777-7777-7777-7777-777777777777"
    _serve(runtime, payload)

    runtime._document_lifecycle_assertions("processing")

    gate = runtime.state.gates[-1]
    assert gate["status"] == "FAILED"
    assert gate["details"]["lineage_matches"] is False
