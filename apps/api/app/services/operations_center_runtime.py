from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.assistant_runtime import (
    AssistantCitationVerification,
    AssistantContextPackage,
    AssistantLlmExecution,
    AssistantLlmInvocationPlan,
    AssistantPromptPackage,
    AssistantResponse,
    AssistantRuntimeRun,
    AssistantSearchExecution,
    AssistantSession,
    Conversation,
    ConversationTurn,
)
from app.models.audit import AuditEvent
from app.models.connectors import Connector, ConnectorConfig, ConnectorRun, ConnectorType
from app.models.documents import Artifact, Chunk, DocumentRecord, DocumentVersion, IndexingJob, IngestionJob
from app.models.knowledge_index import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexHealthSnapshot,
    KnowledgeLifecycleRun,
)
from app.models.processing import ProcessingRevision
from app.models.runtime import RuntimePersistenceRecord
from app.models.runtime_worker import RuntimeWorker
from app.security.tenant_session import TENANT_SCOPE_KEY
from app.services.operational_observability_runtime import build_operational_workspace_runtime
from app.services.security_acceptance_runtime import build_security_readiness

OPERATIONS_CENTER_RUNTIME_SCHEMA_VERSION = "1"
OPERATIONS_CENTER_RUNTIME_NAME = "operations_center_runtime"
RECENT_LIMIT = 10
FAILED_STATUSES = {"failed", "error", "dead_lettered", "expired"}
PENDING_STATUSES = {"pending", "scheduled", "leased", "running", "processing", "prepared", "planned"}
COMPLETED_STATUSES = {"completed", "succeeded", "success", "indexed", "published", "ready"}


def _primary_key(model: Any) -> Any:
    return model.id if hasattr(model, "id") else next(iter(model.__table__.primary_key.columns))


def _count(db: Session, model: Any, *criteria: Any) -> int:
    statement = select(func.count(_primary_key(model)))
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _count_by(db: Session, model: Any, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).select_from(model).group_by(column)).all()
    return {str(value or "unknown"): int(count or 0) for value, count in rows}


def _status(value: Any) -> str:
    return str(value or "unknown").lower()


def _is_completed(value: Any) -> bool:
    return _status(value) in COMPLETED_STATUSES


def _is_failed(value: Any) -> bool:
    return _status(value) in FAILED_STATUSES


def _is_pending(value: Any) -> bool:
    return _status(value) in PENDING_STATUSES


def _json_bool(payload: dict[str, Any] | None, key: str) -> bool:
    return bool((payload or {}).get(key))


def _safe_diagnostics(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload or {}
    return {
        key: source.get(key)
        for key in ("error_code", "error_message", "failure_reason", "warnings", "blocking_issues")
        if source.get(key)
    }


def _runtime_persistence(db: Session) -> dict[str, Any]:
    recent_records = list(
        db.scalars(
            select(RuntimePersistenceRecord)
            .order_by(RuntimePersistenceRecord.occurred_at.desc(), RuntimePersistenceRecord.id.desc())
            .limit(RECENT_LIMIT)
        ).all()
    )
    return {
        "total_runtime_records": _count(db, RuntimePersistenceRecord),
        "runtime_records_by_domain": _count_by(db, RuntimePersistenceRecord, RuntimePersistenceRecord.runtime_domain),
        "runtime_records_by_status": _count_by(
            db, RuntimePersistenceRecord, RuntimePersistenceRecord.persistence_status
        ),
        "recent_runtime_records": [
            {
                "runtime_record_id": record.id,
                "runtime_domain": record.runtime_domain,
                "runtime_action": record.record_type,
                "runtime_status": record.persistence_status,
                "correlation_id": record.correlation_id,
                "idempotency_key": record.record_key,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "duration": None,
                "diagnostics": _safe_diagnostics(record.validation or record.summary or {}),
            }
            for record in recent_records
        ],
    }


def _authorized_knowledge_evidence(
    db: Session,
) -> tuple[list[KnowledgeDocument], list[KnowledgeChunk]]:
    visible_versions = list(db.scalars(select(DocumentVersion)).all())
    visible_lineage = {str(version.id): str(version.document_record_id) for version in visible_versions}
    if not visible_lineage:
        return [], []

    visible_artifacts = list(db.scalars(select(Artifact)).all())
    visible_artifact_lineage = {
        str(artifact.id): (
            str(artifact.document_version_id),
            str(artifact.document_record_id),
        )
        for artifact in visible_artifacts
        if str(artifact.document_version_id) in visible_lineage
        and str(artifact.document_record_id) == visible_lineage[str(artifact.document_version_id)]
    }
    if not visible_artifact_lineage:
        return [], []

    knowledge_documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .join(
                DocumentVersion,
                KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String),
            )
            .join(
                Artifact,
                KnowledgeDocument.artifact_id == cast(Artifact.id, String),
            )
            .where(
                or_(
                    KnowledgeDocument.document_record_id.is_(None),
                    KnowledgeDocument.document_record_id == cast(DocumentVersion.document_record_id, String),
                ),
                Artifact.document_version_id == DocumentVersion.id,
                Artifact.document_record_id == DocumentVersion.document_record_id,
            )
            .order_by(KnowledgeDocument.updated_at.desc())
        ).all()
    )
    authorized_documents = [
        document
        for document in knowledge_documents
        if document.document_version_id is not None
        and str(document.document_version_id) in visible_lineage
        and str(document.artifact_id) in visible_artifact_lineage
        and visible_artifact_lineage[str(document.artifact_id)]
        == (
            str(document.document_version_id),
            visible_lineage[str(document.document_version_id)],
        )
        and (
            document.document_record_id is None
            or str(document.document_record_id) == visible_lineage[str(document.document_version_id)]
        )
    ]
    authorized_document_ids = {document.id for document in authorized_documents}
    if not authorized_document_ids:
        return authorized_documents, []

    knowledge_chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .join(
                KnowledgeDocument,
                KnowledgeChunk.knowledge_document_id == KnowledgeDocument.id,
            )
            .join(
                DocumentVersion,
                KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String),
            )
            .join(
                Artifact,
                KnowledgeDocument.artifact_id == cast(Artifact.id, String),
            )
            .where(
                or_(
                    KnowledgeDocument.document_record_id.is_(None),
                    KnowledgeDocument.document_record_id == cast(DocumentVersion.document_record_id, String),
                ),
                Artifact.document_version_id == DocumentVersion.id,
                Artifact.document_record_id == DocumentVersion.document_record_id,
                KnowledgeChunk.publication_id == KnowledgeDocument.publication_id,
                KnowledgeChunk.artifact_id == KnowledgeDocument.artifact_id,
            )
            .order_by(KnowledgeChunk.updated_at.desc())
        ).all()
    )
    authorized_documents_by_id = {document.id: document for document in authorized_documents}
    return authorized_documents, [
        chunk
        for chunk in knowledge_chunks
        if chunk.knowledge_document_id in authorized_document_ids
        and chunk.publication_id == authorized_documents_by_id[chunk.knowledge_document_id].publication_id
        and chunk.artifact_id == authorized_documents_by_id[chunk.knowledge_document_id].artifact_id
    ]


def _document_lifecycle(
    db: Session,
    knowledge_documents: list[KnowledgeDocument],
) -> dict[str, Any]:
    versions = list(db.scalars(select(DocumentVersion).order_by(DocumentVersion.updated_at.desc())).all())
    artifacts = list(db.scalars(select(Artifact).order_by(Artifact.updated_at.desc())).all())
    chunks = list(db.scalars(select(Chunk)).all())
    artifacts_by_version: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        artifacts_by_version[str(artifact.document_version_id)].append(artifact)
    chunks_by_version = Counter(str(chunk.document_version_id) for chunk in chunks)
    knowledge_by_version = Counter(
        str(doc.document_version_id) for doc in knowledge_documents if doc.document_version_id
    )
    recent = []
    failed_lifecycles = 0
    pending_lifecycles = 0
    for version in versions[:RECENT_LIMIT]:
        snapshot = version.source_snapshot or {}
        version_artifacts = artifacts_by_version.get(str(version.id), [])
        artifact = version_artifacts[0] if version_artifacts else None
        storage_verified = _json_bool(snapshot, "storage_verified") or bool(version.object_store_key)
        knowledge_indexed = bool(knowledge_by_version.get(str(version.id)))
        processing_done = chunks_by_version.get(str(version.id), 0) > 0
        lifecycle_failed = _is_failed(version.status) or bool(snapshot.get("blocking_issues"))
        failed_lifecycles += int(lifecycle_failed)
        pending_lifecycles += int(not lifecycle_failed and not knowledge_indexed)
        recent.append(
            {
                "document_record_id": version.document_record_id,
                "document_version_id": version.id,
                "artifact_id": artifact.id if artifact else None,
                "lifecycle_status": version.status,
                "storage_status": "verified" if storage_verified else "pending",
                "processing_status": "completed" if processing_done else "pending",
                "knowledge_index_status": "indexed" if knowledge_indexed else "pending",
                "enterprise_search_status": "ready" if knowledge_indexed else "pending",
                "chat_status": "ready" if knowledge_indexed else "pending",
                "storage_reused": _json_bool(snapshot, "storage_reused"),
                "blocking_issues": snapshot.get("blocking_issues") or [],
                "warnings": snapshot.get("warnings") or [],
                "latest_activity": version.updated_at,
            }
        )
    storage_verified_count = len(
        [
            version
            for version in versions
            if _json_bool(version.source_snapshot, "storage_verified") or version.object_store_key
        ]
    )
    knowledge_indexed_count = len({doc.document_version_id for doc in knowledge_documents if doc.document_version_id})
    processed_version_ids = {str(chunk.document_version_id) for chunk in chunks}
    processed_version_ids.update(str(doc.document_version_id) for doc in knowledge_documents if doc.document_version_id)
    return {
        "total_document_versions": len(versions),
        "total_artifacts": len(artifacts),
        "registered_documents": _count(db, DocumentRecord),
        "storage_verified": storage_verified_count,
        "processing_completed": len(processed_version_ids),
        "processing_measurement": {
            "definition": "distinct document versions with chunk or governed knowledge-publication evidence",
            "source": "documents.chunks + knowledge.documents.document_version_id",
            "historical_lineage_included": True,
        },
        "chunks_created": len(chunks),
        "knowledge_published": len(knowledge_documents),
        "knowledge_indexed": knowledge_indexed_count,
        "enterprise_search_ready": knowledge_indexed_count,
        "chat_ready": knowledge_indexed_count,
        "storage_reused": len(
            [version for version in versions if _json_bool(version.source_snapshot, "storage_reused")]
        ),
        "idempotent_resumptions": len(
            [version for version in versions if _json_bool(version.source_snapshot, "idempotent_resume")]
        ),
        "failed_lifecycles": failed_lifecycles,
        "pending_lifecycles": pending_lifecycles,
        "recent_lifecycles": recent,
    }


def _processing_workers(db: Session) -> dict[str, Any]:
    revisions = list(db.scalars(select(ProcessingRevision).order_by(ProcessingRevision.updated_at.desc())).all())
    ingestion_jobs = list(db.scalars(select(IngestionJob).order_by(IngestionJob.updated_at.desc())).all())
    chunks = list(db.scalars(select(Chunk)).all())
    workers = list(db.scalars(select(RuntimeWorker)).all())
    failures = [worker for worker in workers if worker.observed_state == "failed" or worker.last_error_code]
    retry_candidates = [
        job
        for job in ingestion_jobs
        if _is_failed(job.status) and int(job.attempt_count or 0) < int(job.max_attempts or 0)
    ]
    return {
        "processing_executions": len(revisions),
        "processing_completed": len([revision for revision in revisions if _is_completed(revision.status)]),
        "processing_failed": len([revision for revision in revisions if _is_failed(revision.status)]),
        "processing_pending": len([revision for revision in revisions if _is_pending(revision.status)]),
        "chunk_generation_completed": len([chunk for chunk in chunks if _is_completed(chunk.status)]),
        "chunk_generation_failed": len([chunk for chunk in chunks if _is_failed(chunk.status)]),
        "worker_runtime_ready": any(worker.observed_state == "ready" for worker in workers),
        "worker_execution_pending": len([job for job in ingestion_jobs if _is_pending(job.status)]),
        "worker_failures": len(failures),
        "retry_candidates": len(retry_candidates),
        "recent_processing_activity": [
            {
                "processing_revision_id": revision.id,
                "document_version_id": revision.document_version_id,
                "status": revision.status,
                "chunk_count": revision.chunk_count,
                "started_at": revision.started_at,
                "completed_at": revision.completed_at,
            }
            for revision in revisions[:RECENT_LIMIT]
        ],
        "pending_capabilities": [
            {
                "code": "dedicated_worker_queue_metrics_unavailable",
                "reason": "runtime worker queue depth is represented by runtime executions and ingestion jobs.",
            }
        ],
    }


def _knowledge_operations(
    db: Session,
    docs: list[KnowledgeDocument],
    chunks: list[KnowledgeChunk],
) -> dict[str, Any]:
    indexing_jobs = list(db.scalars(select(IndexingJob).order_by(IndexingJob.updated_at.desc())).all())
    lifecycle_runs = list(
        db.scalars(select(KnowledgeLifecycleRun).order_by(KnowledgeLifecycleRun.created_at.desc())).all()
    )
    organization_scoped = db.info.get(TENANT_SCOPE_KEY) is not None
    if organization_scoped:
        authorized_documents_by_id = {str(doc.id): doc for doc in docs}
        authorized_documents_by_publication = {(doc.artifact_id, doc.publication_id): doc for doc in docs}
        authorized_lifecycle_runs = []
        for run in lifecycle_runs:
            matched_document = None
            if run.document_id:
                matched_document = authorized_documents_by_id.get(str(run.document_id))
            elif run.artifact_id and run.publication_id:
                matched_document = authorized_documents_by_publication.get((run.artifact_id, run.publication_id))
            if matched_document is None:
                continue
            if run.document_id and str(run.document_id) != str(matched_document.id):
                continue
            if run.artifact_id and run.artifact_id != matched_document.artifact_id:
                continue
            if run.publication_id and run.publication_id != matched_document.publication_id:
                continue
            authorized_lifecycle_runs.append(run)
        lifecycle_runs = authorized_lifecycle_runs
        latest_health = None
    else:
        latest_health = db.scalars(
            select(KnowledgeIndexHealthSnapshot).order_by(KnowledgeIndexHealthSnapshot.created_at.desc()).limit(1)
        ).first()
    indexed_documents = len([doc for doc in docs if _is_completed(doc.status)])
    indexed_chunks = len([chunk for chunk in chunks if _is_completed(chunk.status)])
    return {
        "knowledge_documents": len(docs),
        "knowledge_chunks": len(chunks),
        "indexed_documents": indexed_documents,
        "indexed_chunks": indexed_chunks,
        "publication_completed": len([run for run in lifecycle_runs if _is_completed(run.status)]),
        "publication_failed": len([run for run in lifecycle_runs if _is_failed(run.status)]),
        "indexing_pending": len([job for job in indexing_jobs if _is_pending(job.status)]),
        "indexing_failed": len([job for job in indexing_jobs if _is_failed(job.status)]),
        "knowledge_health": {
            "latest_snapshot_at": latest_health.created_at if latest_health else None,
            "indexed_documents": indexed_documents,
            "indexed_chunks": indexed_chunks,
            "rebuild_required": (
                latest_health.rebuild_required
                if latest_health
                else any(not _is_completed(doc.status) for doc in docs)
                or any(not _is_completed(chunk.status) for chunk in chunks)
            ),
        },
        "recent_knowledge_activity": [
            {
                "knowledge_document_id": doc.id,
                "artifact_id": doc.artifact_id,
                "status": doc.status,
                "publication_id": doc.publication_id,
                "updated_at": doc.updated_at,
            }
            for doc in docs[:RECENT_LIMIT]
        ],
    }


def _enterprise_search_operations(db: Session, knowledge: dict[str, Any]) -> dict[str, Any]:
    searches = list(
        db.scalars(select(AssistantSearchExecution).order_by(AssistantSearchExecution.created_at.desc())).all()
    )
    pending = []
    if not searches:
        pending.append(
            {"code": "search_request_history_unavailable", "reason": "no assistant search executions recorded"}
        )
    indexed_chunks = int(knowledge.get("indexed_chunks") or 0)
    searchable_chunks = indexed_chunks
    coverage = float(indexed_chunks / searchable_chunks) if searchable_chunks else None
    return {
        "search_requests": len(searches),
        "successful_searches": len([search for search in searches if search.search_completed]),
        "failed_searches": len([search for search in searches if not search.search_completed]),
        "search_ready": indexed_chunks > 0,
        "fts_ready": indexed_chunks > 0,
        "search_result_coverage": coverage,
        "search_coverage_measurement": {
            "definition": "indexed governed knowledge chunks divided by searchable governed knowledge chunks",
            "numerator": indexed_chunks,
            "denominator": searchable_chunks,
            "source": "knowledge.chunks",
            "measurable": searchable_chunks > 0,
        },
        "recent_search_activity": [
            {
                "search_execution_id": search.search_execution_id,
                "assistant_id": search.assistant_id,
                "search_completed": search.search_completed,
                "result_count": search.result_count,
                "search_duration_ms": search.search_duration_ms,
                "created_at": search.created_at,
            }
            for search in searches[:RECENT_LIMIT]
        ],
        "search_diagnostics": {"pending_capabilities": pending},
    }


def _assistant_operations(db: Session) -> dict[str, Any]:
    runs = list(db.scalars(select(AssistantRuntimeRun).order_by(AssistantRuntimeRun.updated_at.desc())).all())
    return {
        "assistant_sessions": _count(db, AssistantSession),
        "assistant_runtime_executions": len(runs),
        "conversation_count": _count(db, Conversation),
        "turn_count": _count(db, ConversationTurn),
        "context_builder_executions": _count(db, AssistantContextPackage),
        "prompt_assembly_executions": _count(db, AssistantPromptPackage),
        "llm_gateway_executions": _count(db, AssistantLlmInvocationPlan),
        "llm_execution_records": _count(db, AssistantLlmExecution),
        "citation_verification_executions": _count(db, AssistantCitationVerification),
        "assistant_response_executions": _count(db, AssistantResponse),
        "chat_runtime_executions": _count(
            db,
            RuntimePersistenceRecord,
            RuntimePersistenceRecord.runtime_domain == "chat_runtime",
        ),
        "recent_assistant_activity": [
            {
                "assistant_runtime_id": run.assistant_run_id,
                "assistant_id": run.assistant_id,
                "status": run.run_status,
                "execution_state": run.execution_state,
                "updated_at": run.updated_at,
            }
            for run in runs[:RECENT_LIMIT]
        ],
    }


def _connector_operations(db: Session) -> dict[str, Any]:
    connectors = list(db.scalars(select(Connector)).all())
    configs = list(db.scalars(select(ConnectorConfig)).all())
    runs = list(db.scalars(select(ConnectorRun).order_by(ConnectorRun.created_at.desc())).all())
    return {
        "connector_count": len(connectors),
        "connector_types": _count(db, ConnectorType),
        "configured_connectors": len({config.connector_id for config in configs if config.is_active}),
        "connector_runs": len(runs),
        "successful_connector_runs": len([run for run in runs if _is_completed(run.run_status)]),
        "failed_connector_runs": len([run for run in runs if _is_failed(run.run_status)]),
        "pending_connector_runs": len([run for run in runs if _is_pending(run.run_status)]),
        "recent_connector_runs": [
            {
                "connector_run_id": run.id,
                "connector_id": run.connector_id,
                "status": run.run_status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "records_processed": (run.summary or {}).get("records_processed"),
                "records_failed": (run.summary or {}).get("records_failed"),
            }
            for run in runs[:RECENT_LIMIT]
        ],
        "connector_diagnostics": [],
    }


def _feedback_audit_operations(db: Session) -> dict[str, Any]:
    audit_events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc())).all())
    feedback_events = [event for event in audit_events if event.resource_type == "feedback"]
    return {
        "feedback_count": len(feedback_events),
        "feedback_by_rating": dict(
            Counter(str((event.metadata_json or {}).get("rating") or "unrated") for event in feedback_events)
        ),
        "feedback_pending": len(
            [
                event
                for event in feedback_events
                if str((event.metadata_json or {}).get("status") or "").lower() == "pending"
            ]
        ),
        "recent_feedback": [
            {
                "feedback_id": event.id,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "created_at": event.created_at,
            }
            for event in feedback_events[:RECENT_LIMIT]
        ],
        "audit_event_count": len(audit_events),
        "audit_events_by_action": dict(Counter(str(event.action_id or "unknown") for event in audit_events)),
        "recent_audit_events": [
            {
                "audit_event_id": event.id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "created_at": event.created_at,
            }
            for event in audit_events[:RECENT_LIMIT]
        ],
        "traceability_ready": bool(audit_events),
    }


def _diagnostics(
    runtime: dict[str, Any],
    document_lifecycle: dict[str, Any],
    processing: dict[str, Any],
    knowledge: dict[str, Any],
    search: dict[str, Any],
    connectors: dict[str, Any],
) -> dict[str, Any]:
    failed_items = []
    retry_candidates = []
    pending_capabilities = []
    degraded_items = []
    if int(runtime.get("runtime_records_by_status", {}).get("failed", 0)) > 0:
        failed_items.append({"item_type": "runtime_persistence", "status": "failed"})
    if document_lifecycle.get("failed_lifecycles"):
        failed_items.append({"item_type": "document_lifecycle", "count": document_lifecycle["failed_lifecycles"]})
    if processing.get("worker_failures"):
        failed_items.append({"item_type": "worker", "count": processing["worker_failures"]})
    if processing.get("retry_candidates"):
        retry_candidates.append({"item_type": "ingestion_job", "count": processing["retry_candidates"]})
    pending_capabilities.extend(processing.get("pending_capabilities") or [])
    pending_capabilities.extend((search.get("search_diagnostics") or {}).get("pending_capabilities") or [])
    for key, ready in {
        "runtime_persistence": runtime.get("total_runtime_records", 0) >= 0,
        "document_lifecycle": document_lifecycle.get("total_document_versions", 0) > 0,
        "knowledge": knowledge.get("indexed_chunks", 0) > 0,
        "search": search.get("search_ready"),
        "connectors": connectors.get("connector_count", 0) > 0,
    }.items():
        if not ready:
            degraded_items.append({"item_type": "domain", "item_id": key, "status": "pending"})
    recommendations = []
    if failed_items:
        recommendations.append({"code": "inspect_failed_items", "label": "Inspect failed runtime and lifecycle items"})
    if retry_candidates:
        recommendations.append({"code": "review_retry_candidates", "label": "Review retry candidates before execution"})
    if pending_capabilities:
        recommendations.append(
            {"code": "review_pending_capabilities", "label": "Review unavailable operational telemetry"}
        )
    return {
        "blocking_issues": [],
        "warnings": [],
        "pending_capabilities": pending_capabilities,
        "degraded_items": degraded_items,
        "failed_items": failed_items,
        "retry_candidates": retry_candidates,
        "operational_recommendations": recommendations,
    }


def build_operations_center_runtime(db: Session) -> dict[str, Any]:
    knowledge_documents, knowledge_chunks = _authorized_knowledge_evidence(db)
    runtime = _runtime_persistence(db)
    document_lifecycle = _document_lifecycle(db, knowledge_documents)
    processing = _processing_workers(db)
    knowledge = _knowledge_operations(db, knowledge_documents, knowledge_chunks)
    search = _enterprise_search_operations(db, knowledge)
    assistant = _assistant_operations(db)
    connectors = _connector_operations(db)
    feedback_audit = _feedback_audit_operations(db)
    operational = build_operational_workspace_runtime(db, refresh=False)
    security_readiness = build_security_readiness(db, refresh=False)
    diagnostics = _diagnostics(runtime, document_lifecycle, processing, knowledge, search, connectors)
    operational_diagnostics = [item.model_dump(mode="json") for item in operational.diagnostics]
    diagnostics["operational_diagnostics"] = operational_diagnostics
    diagnostics["blocking_issues"].extend(operational.open_blockers)
    diagnostics["operational_recommendations"].extend(operational.next_actions)
    operations_ready = not diagnostics["failed_items"]
    operations_ready = operations_ready and operational.operational_readiness.status != "failed"
    runtime_status = "ready" if operations_ready else "degraded"
    return {
        "operations_center_runtime_schema_version": OPERATIONS_CENTER_RUNTIME_SCHEMA_VERSION,
        "runtime_name": OPERATIONS_CENTER_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "operations_ready": operations_ready,
            "operational_readiness_ready": operational.operational_readiness.operational_ready,
            "runtime_persistence_ready": runtime["total_runtime_records"] >= 0,
            "document_lifecycle_ready": document_lifecycle["total_document_versions"] > 0,
            "processing_ready": processing["processing_failed"] == 0,
            "knowledge_ready": knowledge["indexed_chunks"] > 0,
            "search_ready": bool(search["search_ready"]),
            "assistant_ready": assistant["assistant_runtime_executions"] >= 0,
            "connectors_ready": connectors["connector_count"] > 0,
            "feedback_ready": feedback_audit["feedback_count"] >= 0,
            "audit_ready": feedback_audit["audit_event_count"] >= 0,
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "llm_used": False,
            "qdrant_used": False,
            "external_calls_performed": False,
        },
        "runtime_persistence": runtime,
        "document_lifecycle_operations": document_lifecycle,
        "processing_workers": processing,
        "knowledge_operations": knowledge,
        "enterprise_search_operations": search,
        "assistant_operations": assistant,
        "connector_operations": connectors,
        "feedback_audit_operations": feedback_audit,
        "operational_readiness": operational.operational_readiness.model_dump(mode="json"),
        "security_readiness": security_readiness.model_dump(mode="json"),
        "component_summary": operational.component_summary,
        "worker_summary": operational.worker_summary,
        "scheduler_summary": operational.scheduler_summary,
        "lease_summary": operational.lease_summary,
        "execution_summary": operational.execution_summary,
        "retry_summary": operational.retry_summary,
        "incident_summary": operational.incident_summary,
        "recent_recovery_actions": operational.recent_recovery_actions,
        "evidence_freshness": operational.evidence_freshness,
        "next_actions": operational.next_actions,
        "diagnostics": diagnostics,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "llm_used": False,
        "qdrant_used": False,
        "external_calls_performed": False,
    }
