from __future__ import annotations

from app.services.workflow_studio_runtime import _evidence_map


def _workflow_evidence(
    *,
    documents: dict[str, int] | None = None,
    processing: dict[str, int] | None = None,
    knowledge: dict[str, int] | None = None,
) -> dict[str, dict[str, object]]:
    operations = {
        "document_lifecycle_operations": documents or {},
        "processing_workers": processing or {},
        "knowledge_operations": knowledge or {},
    }
    return _evidence_map(operations, {}, {}, {}, {})


def test_chunk_generation_uses_equivalent_persisted_chunk_count_when_primary_is_zero() -> None:
    evidence = _workflow_evidence(
        documents={"chunks_created": 0},
        processing={"chunk_generation_completed": 4},
    )

    assert evidence["chunk_generation"] == {
        "count": 4,
        "ready": True,
        "source": "chunk_runtime",
    }


def test_publication_uses_persisted_documents_when_document_summary_is_stale() -> None:
    evidence = _workflow_evidence(
        documents={"knowledge_published": 0},
        knowledge={"knowledge_documents": 2, "publication_completed": 7},
    )

    assert evidence["knowledge_publication"] == {
        "count": 2,
        "ready": True,
        "source": "knowledge_publication_runtime",
    }
    assert evidence["chunk_generation"]["ready"] is True


def test_completed_knowledge_operations_do_not_replace_publication_evidence() -> None:
    evidence = _workflow_evidence(
        documents={"knowledge_published": 0},
        knowledge={"knowledge_documents": 0, "publication_completed": 7},
    )

    assert evidence["knowledge_publication"] == {
        "count": 0,
        "ready": False,
        "source": "knowledge_publication_runtime",
    }
    assert evidence["chunk_generation"]["ready"] is False


def test_index_uses_authorized_persisted_document_evidence_without_counting_chunks() -> None:
    evidence = _workflow_evidence(
        documents={"knowledge_indexed": 0},
        knowledge={"indexed_documents": 3, "indexed_chunks": 11},
    )

    assert evidence["knowledge_index"] == {
        "count": 3,
        "ready": True,
        "source": "postgresql_knowledge_index",
    }
    assert evidence["knowledge_publication"] == {
        "count": 3,
        "ready": True,
        "source": "knowledge_publication_runtime",
    }
    assert evidence["chunk_generation"] == {
        "count": 11,
        "ready": True,
        "source": "chunk_runtime",
    }


def test_lifecycle_capabilities_are_not_ready_without_persisted_evidence() -> None:
    evidence = _workflow_evidence()

    for capability in ("chunk_generation", "knowledge_publication", "knowledge_index"):
        assert evidence[capability]["count"] == 0
        assert evidence[capability]["ready"] is False


def test_lifecycle_counts_keep_stable_units_when_cardinalities_differ() -> None:
    evidence = _workflow_evidence(
        documents={
            "chunks_created": 5,
            "knowledge_published": 2,
            "knowledge_indexed": 1,
        },
        processing={"chunk_generation_completed": 4},
        knowledge={
            "knowledge_chunks": 12,
            "knowledge_documents": 2,
            "publication_completed": 9,
            "indexed_documents": 2,
            "indexed_chunks": 10,
        },
    )

    assert evidence["chunk_generation"]["count"] == 5
    assert evidence["knowledge_publication"]["count"] == 2
    assert evidence["knowledge_index"]["count"] == 1
    assert all(
        "evidence_counts" not in evidence[capability]
        for capability in ("chunk_generation", "knowledge_publication", "knowledge_index")
    )
