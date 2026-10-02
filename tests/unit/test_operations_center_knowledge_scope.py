from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.models.assistant_runtime import AssistantSearchExecution
from app.models.documents import Artifact, Chunk, DocumentRecord, DocumentVersion, IndexingJob, IngestionJob
from app.models.knowledge_index import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexHealthSnapshot,
    KnowledgeLifecycleRun,
)
from app.models.processing import ProcessingRevision
from app.models.runtime_worker import RuntimeWorker
from app.security.tenant_session import TENANT_SCOPE_KEY
from app.services import operations_center_runtime as operations_runtime
from app.services.workflow_studio_runtime import _evidence_map, _workflow_catalog, _workflow_inventory

_UNSET = object()


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)

    def first(self):
        return self.values[0] if self.values else None


class FakeSession:
    def __init__(self, values_by_model, organization_id):
        self.values_by_model = values_by_model
        self.info = {TENANT_SCOPE_KEY: organization_id}

    def scalars(self, statement):
        model = statement.column_descriptions[0]["entity"]
        return FakeScalarResult(self.values_by_model.get(model, []))

    def scalar(self, _statement):
        return 0


def _version(organization_id: uuid.UUID):
    identifier = uuid.uuid4()
    record_id = uuid.uuid4()
    return SimpleNamespace(
        id=identifier,
        organization_id=organization_id,
        document_record_id=record_id,
        source_snapshot={"storage_verified": True},
        object_store_key=f"documents/{identifier}",
        status="indexed",
        updated_at=datetime.now(UTC),
    )


def _artifact(
    version,
    *,
    artifact_id=_UNSET,
    document_version_id=_UNSET,
    document_record_id=_UNSET,
):
    return SimpleNamespace(
        id=uuid.uuid4() if artifact_id is _UNSET else artifact_id,
        organization_id=version.organization_id,
        document_version_id=(version.id if document_version_id is _UNSET else document_version_id),
        document_record_id=(version.document_record_id if document_record_id is _UNSET else document_record_id),
        updated_at=datetime.now(UTC),
    )


def _knowledge_document(
    version,
    artifact,
    *,
    document_version_id=_UNSET,
    document_record_id=_UNSET,
    artifact_id=_UNSET,
):
    identifier = uuid.uuid4()
    return SimpleNamespace(
        id=identifier,
        document_version_id=(str(version.id) if document_version_id is _UNSET else document_version_id),
        document_record_id=(str(version.document_record_id) if document_record_id is _UNSET else document_record_id),
        artifact_id=str(artifact.id) if artifact_id is _UNSET else artifact_id,
        publication_id=f"publication-{identifier}",
        status="indexed",
        updated_at=datetime.now(UTC),
    )


def _knowledge_chunk(
    document,
    *,
    publication_id=_UNSET,
    artifact_id=_UNSET,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_document_id=document.id,
        publication_id=(document.publication_id if publication_id is _UNSET else publication_id),
        artifact_id=document.artifact_id if artifact_id is _UNSET else artifact_id,
        status="indexed",
        updated_at=datetime.now(UTC),
    )


def _lifecycle_run(
    document,
    *,
    publication_id=_UNSET,
    artifact_id=_UNSET,
    document_id=_UNSET,
):
    return SimpleNamespace(
        publication_id=(document.publication_id if publication_id is _UNSET else publication_id),
        artifact_id=document.artifact_id if artifact_id is _UNSET else artifact_id,
        document_id=str(document.id) if document_id is _UNSET else document_id,
        status="completed",
    )


def _session(
    organization_id,
    visible_versions,
    knowledge_documents,
    knowledge_chunks,
    source_chunks=(),
    lifecycle_runs=(),
    health_snapshots=(),
    visible_artifacts=(),
):
    return FakeSession(
        {
            DocumentVersion: list(visible_versions),
            Artifact: list(visible_artifacts),
            Chunk: list(source_chunks),
            DocumentRecord: [],
            KnowledgeDocument: list(knowledge_documents),
            KnowledgeChunk: list(knowledge_chunks),
            IndexingJob: [],
            KnowledgeLifecycleRun: list(lifecycle_runs),
            KnowledgeIndexHealthSnapshot: list(health_snapshots),
            AssistantSearchExecution: [],
            ProcessingRevision: [],
            IngestionJob: [],
            RuntimeWorker: [],
        },
        organization_id,
    )


class DumpableState:
    def __init__(self, **values):
        self.values = values
        for key, value in values.items():
            setattr(self, key, value)

    def model_dump(self, *, mode):
        assert mode == "json"
        return dict(self.values)


def _build_operations_projection(session, monkeypatch):
    monkeypatch.setattr(
        operations_runtime,
        "_runtime_persistence",
        lambda _db: {
            "total_runtime_records": 0,
            "runtime_records_by_domain": {},
            "runtime_records_by_status": {},
            "recent_runtime_records": [],
        },
    )
    monkeypatch.setattr(
        operations_runtime,
        "_assistant_operations",
        lambda _db: {"assistant_runtime_executions": 0},
    )
    monkeypatch.setattr(
        operations_runtime,
        "_connector_operations",
        lambda _db: {"connector_count": 0},
    )
    monkeypatch.setattr(
        operations_runtime,
        "_feedback_audit_operations",
        lambda _db: {"feedback_count": 0, "audit_event_count": 0},
    )
    operational = SimpleNamespace(
        diagnostics=[],
        open_blockers=[],
        next_actions=[],
        operational_readiness=DumpableState(status="ready", operational_ready=True),
        component_summary={},
        worker_summary={},
        scheduler_summary={},
        lease_summary={},
        execution_summary={},
        retry_summary={},
        incident_summary={},
        recent_recovery_actions=[],
        evidence_freshness={},
    )
    monkeypatch.setattr(
        operations_runtime,
        "build_operational_workspace_runtime",
        lambda _db, *, refresh: operational,
    )
    monkeypatch.setattr(
        operations_runtime,
        "build_security_readiness",
        lambda _db, *, refresh: DumpableState(status="ready"),
    )
    return operations_runtime.build_operations_center_runtime(session)


def test_each_organization_projects_only_its_authorized_knowledge_lineage(monkeypatch) -> None:
    organization_a = uuid.uuid4()
    organization_b = uuid.uuid4()
    version_a = _version(organization_a)
    version_b = _version(organization_b)
    artifact_a = _artifact(version_a)
    artifact_b = _artifact(version_b)
    document_a = _knowledge_document(version_a, artifact_a)
    document_b = _knowledge_document(version_b, artifact_b)
    chunk_a = _knowledge_chunk(document_a)
    chunk_b = _knowledge_chunk(document_b)
    all_documents = [document_a, document_b]
    all_chunks = [chunk_a, chunk_b]

    projection_a = _build_operations_projection(
        _session(
            organization_a,
            [version_a],
            all_documents,
            all_chunks,
            visible_artifacts=[artifact_a],
        ),
        monkeypatch,
    )
    projection_b = _build_operations_projection(
        _session(
            organization_b,
            [version_b],
            all_documents,
            all_chunks,
            visible_artifacts=[artifact_b],
        ),
        monkeypatch,
    )

    assert projection_a["knowledge_operations"]["knowledge_documents"] == 1
    assert projection_a["knowledge_operations"]["knowledge_chunks"] == 1
    assert (
        projection_a["knowledge_operations"]["recent_knowledge_activity"][0]["knowledge_document_id"] == document_a.id
    )
    assert projection_b["knowledge_operations"]["knowledge_documents"] == 1
    assert projection_b["knowledge_operations"]["knowledge_chunks"] == 1
    assert (
        projection_b["knowledge_operations"]["recent_knowledge_activity"][0]["knowledge_document_id"] == document_b.id
    )


def test_document_without_document_version_lineage_is_excluded(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact, document_version_id=None)
    chunk = _knowledge_chunk(document)

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [chunk],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["document_lifecycle_operations"]["knowledge_published"] == 0
    assert projection["document_lifecycle_operations"]["knowledge_indexed"] == 0
    assert projection["knowledge_operations"]["knowledge_documents"] == 0
    assert projection["knowledge_operations"]["knowledge_chunks"] == 0
    assert projection["enterprise_search_operations"]["search_ready"] is False


def test_document_linked_to_another_organization_version_is_excluded(monkeypatch) -> None:
    organization_a = uuid.uuid4()
    organization_b = uuid.uuid4()
    visible_version = _version(organization_a)
    external_version = _version(organization_b)
    visible_artifact = _artifact(visible_version)
    external_artifact = _artifact(external_version)
    external_document = _knowledge_document(external_version, external_artifact)

    projection = _build_operations_projection(
        _session(
            organization_a,
            [visible_version],
            [external_document],
            [],
            visible_artifacts=[visible_artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_documents"] == 0
    assert projection["document_lifecycle_operations"]["knowledge_published"] == 0


def test_document_with_mismatched_record_lineage_is_excluded(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(
        version,
        artifact,
        document_record_id=str(uuid.uuid4()),
    )

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_documents"] == 0
    assert projection["document_lifecycle_operations"]["knowledge_published"] == 0


def test_chunk_of_excluded_knowledge_document_is_not_counted(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    visible_version = _version(organization_id)
    artifact = _artifact(visible_version)
    excluded_document = _knowledge_document(
        visible_version,
        artifact,
        document_version_id=None,
    )
    excluded_chunk = _knowledge_chunk(excluded_document)

    projection = _build_operations_projection(
        _session(
            organization_id,
            [visible_version],
            [excluded_document],
            [excluded_chunk],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_chunks"] == 0
    assert projection["knowledge_operations"]["indexed_chunks"] == 0


def test_document_with_artifact_from_another_organization_is_excluded(
    monkeypatch,
) -> None:
    organization_a = uuid.uuid4()
    organization_b = uuid.uuid4()
    visible_version = _version(organization_a)
    external_version = _version(organization_b)
    visible_artifact = _artifact(visible_version)
    external_artifact = _artifact(external_version)
    document = _knowledge_document(visible_version, external_artifact)

    projection = _build_operations_projection(
        _session(
            organization_a,
            [visible_version],
            [document],
            [],
            visible_artifacts=[visible_artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_documents"] == 0
    assert projection["document_lifecycle_operations"]["knowledge_published"] == 0


def test_document_with_visible_artifact_from_another_version_is_excluded(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    document_version = _version(organization_id)
    artifact_version = _version(organization_id)
    mismatched_artifact = _artifact(artifact_version)
    document = _knowledge_document(document_version, mismatched_artifact)

    projection = _build_operations_projection(
        _session(
            organization_id,
            [document_version, artifact_version],
            [document],
            [],
            visible_artifacts=[mismatched_artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_documents"] == 0
    assert projection["document_lifecycle_operations"]["knowledge_indexed"] == 0


def test_chunks_with_inconsistent_publication_or_artifact_are_excluded(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    publication_mismatch = _knowledge_chunk(
        document,
        publication_id="publication-external",
    )
    artifact_mismatch = _knowledge_chunk(
        document,
        artifact_id=str(uuid.uuid4()),
    )

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [publication_mismatch, artifact_mismatch],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["knowledge_documents"] == 1
    assert projection["knowledge_operations"]["knowledge_chunks"] == 0
    assert projection["knowledge_operations"]["indexed_chunks"] == 0
    assert projection["enterprise_search_operations"]["search_ready"] is False


def test_lifecycle_run_with_authorized_publication_and_external_artifact_is_excluded(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    conflicting_run = _lifecycle_run(
        document,
        artifact_id=str(uuid.uuid4()),
        document_id=None,
    )

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [],
            lifecycle_runs=[conflicting_run],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["publication_completed"] == 0


def test_lifecycle_run_with_authorized_artifact_and_external_document_is_excluded(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    conflicting_run = _lifecycle_run(
        document,
        document_id=str(uuid.uuid4()),
    )

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [],
            lifecycle_runs=[conflicting_run],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["publication_completed"] == 0


def test_lifecycle_runs_without_unambiguous_lineage_are_excluded(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    insufficient_runs = [
        _lifecycle_run(document, artifact_id=None, document_id=None),
        _lifecycle_run(document, publication_id=None, document_id=None),
        _lifecycle_run(
            document,
            publication_id=None,
            artifact_id=None,
            document_id=None,
        ),
    ]

    projection = _build_operations_projection(
        _session(
            organization_id,
            [version],
            [document],
            [],
            lifecycle_runs=insufficient_runs,
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["publication_completed"] == 0


def test_platform_scope_preserves_unfiltered_lifecycle_runs(monkeypatch) -> None:
    version = _version(uuid.uuid4())
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    platform_run = _lifecycle_run(
        document,
        publication_id=None,
        artifact_id=None,
        document_id=None,
    )

    projection = _build_operations_projection(
        _session(
            None,
            [version],
            [document],
            [],
            lifecycle_runs=[platform_run],
            visible_artifacts=[artifact],
        ),
        monkeypatch,
    )

    assert projection["knowledge_operations"]["publication_completed"] == 1


def test_authorized_persisted_evidence_readies_the_complete_workflow_chain(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    version = _version(organization_id)
    artifact = _artifact(version)
    document = _knowledge_document(version, artifact)
    knowledge_chunk = _knowledge_chunk(document)
    lifecycle_run = _lifecycle_run(document)
    source_chunk = SimpleNamespace(
        document_version_id=version.id,
        status="completed",
    )
    session = _session(
        organization_id,
        [version],
        [document],
        [knowledge_chunk],
        [source_chunk],
        lifecycle_runs=[lifecycle_run],
        visible_artifacts=[artifact],
    )
    operations = _build_operations_projection(session, monkeypatch)
    evidence = _evidence_map(operations, {}, {}, {}, {})
    inventory = {item["workflow_key"]: item for item in _workflow_inventory(_workflow_catalog(), evidence)}

    assert operations["knowledge_operations"]["publication_completed"] == 1
    for capability in (
        "chunk_generation",
        "knowledge_publication",
        "knowledge_index",
        "enterprise_search",
    ):
        assert inventory[capability]["status"] == "ready"
        assert inventory[capability]["ready"] is True


def test_global_or_orphan_evidence_does_not_create_authorized_false_positives(
    monkeypatch,
) -> None:
    organization_a = uuid.uuid4()
    organization_b = uuid.uuid4()
    visible_version = _version(organization_a)
    external_version = _version(organization_b)
    visible_artifact = _artifact(visible_version)
    external_artifact = _artifact(external_version)
    external_document = _knowledge_document(external_version, external_artifact)
    orphan_document = _knowledge_document(
        visible_version,
        visible_artifact,
        document_version_id=None,
    )
    external_chunk = _knowledge_chunk(external_document)
    orphan_chunk = _knowledge_chunk(orphan_document)
    global_lifecycle_run = SimpleNamespace(
        publication_id=external_document.publication_id,
        artifact_id=external_document.artifact_id,
        document_id=str(external_document.id),
        status="completed",
    )
    global_health_snapshot = SimpleNamespace(
        indexed_documents=99,
        indexed_chunks=999,
        rebuild_required=False,
        created_at=datetime.now(UTC),
    )

    operations = _build_operations_projection(
        _session(
            organization_a,
            [visible_version],
            [external_document, orphan_document],
            [external_chunk, orphan_chunk],
            lifecycle_runs=[global_lifecycle_run],
            health_snapshots=[global_health_snapshot],
            visible_artifacts=[visible_artifact],
        ),
        monkeypatch,
    )
    evidence = _evidence_map(operations, {}, {}, {}, {})

    for capability in (
        "chunk_generation",
        "knowledge_publication",
        "knowledge_index",
        "enterprise_search",
    ):
        assert evidence[capability]["ready"] is False
    assert operations["knowledge_operations"]["publication_completed"] == 0
    assert operations["knowledge_operations"]["knowledge_health"]["indexed_documents"] == 0
    assert operations["knowledge_operations"]["knowledge_health"]["indexed_chunks"] == 0
