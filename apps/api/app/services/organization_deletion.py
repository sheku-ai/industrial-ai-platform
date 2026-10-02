from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import MetaData, String, Table, cast, delete, func, inspect, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.core import Organization
from app.models.organization_lifecycle import OrganizationDeletionExecution
from app.schemas.core import OrganizationDeletionExecutionRead, OrganizationDeletionRequest

DELETION_EXECUTION_TABLE = "core.organization_deletion_executions"
PROTECTED_MARKERS = ("system", "protected", "reference_tenant", "canonical_product_reference")
REMOTE_STORAGE_PROVIDERS = {"s3", "minio", "object_storage"}
STORAGE_PREVIEW_BLOCKER_CODES = {
    "filesystem_object_binary_missing",
    "filesystem_object_key_escapes_storage_root",
    "filesystem_object_metadata_missing",
    "object_storage_inventory_unavailable",
    "object_storage_object_missing",
    "unsupported_object_storage_provider",
}

PREVIEW_TABLES = {
    "organization_nodes": ("core.organization_nodes",),
    "organization_relationships": ("core.organization_relationships",),
    "roles": ("security.roles",),
    "role_assignments": ("security.role_assignments",),
    "document_types": ("documents.document_types",),
    "metadata_templates": ("documents.metadata_templates",),
    "documents": ("documents.document_records",),
    "document_versions": ("documents.document_versions",),
    "upload_sessions": ("runtime.executions",),
    "storage_objects": (),
    "processing_executions": ("documents.processing_revisions", "documents.ingestion_jobs"),
    "chunks": ("documents.chunks",),
    "knowledge_documents": ("knowledge.documents",),
    "knowledge_chunks": ("knowledge.chunks",),
    "search_records": ("knowledge.chunks",),
    "assistants": ("ai.assistant_definitions", "ai.assistants"),
    "conversations": ("ai.conversations",),
    "turns": ("ai.conversation_turns",),
    "assistant_responses": ("ai.assistant_responses",),
    "audit_records": ("audit.audit_events", "audit.audit_history"),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _request_hash(organization_id: uuid.UUID, requested_by: str) -> str:
    return _stable_hash({"organization_id": str(organization_id), "requested_by": requested_by})


def _validate_deletable(organization: Organization) -> list[dict[str, Any]]:
    config = dict(organization.config or {})
    blockers: list[dict[str, Any]] = []
    if config.get("deletion_allowed") is not True:
        blockers.append({"code": "deletion_not_allowed", "message": "Organization deletion is not enabled."})
    protected = [marker for marker in PROTECTED_MARKERS if config.get(marker) is True]
    if protected:
        blockers.append(
            {
                "code": "protected_organization",
                "message": "Protected or system organizations cannot be deleted.",
                "markers": protected,
            }
        )
    return blockers


def _reflect_metadata(db: Session) -> MetaData:
    bind = db.get_bind()
    metadata = MetaData()
    schemas = [
        schema
        for schema in inspect(bind).get_schema_names()
        if schema not in {"information_schema", "pg_catalog", "pg_toast"} and not schema.startswith("pg_")
    ]
    for schema in schemas:
        metadata.reflect(bind=bind, schema=schema)
    return metadata


def _scope_predicates(metadata: MetaData, organization_id: uuid.UUID) -> dict[str, Any]:
    predicates: dict[str, Any] = {}
    for key, table in metadata.tables.items():
        if key == DELETION_EXECUTION_TABLE:
            continue
        if "organization_id" in table.c:
            predicates[key] = table.c.organization_id == organization_id

    document_records = metadata.tables.get("documents.document_records")
    document_artifacts = metadata.tables.get("documents.artifacts")
    knowledge_documents = metadata.tables.get("knowledge.documents")
    if document_records is not None and knowledge_documents is not None:
        document_scope = predicates.get("documents.document_records")
        if document_scope is not None:
            conditions = [
                cast(knowledge_documents.c.document_record_id, String).in_(
                    select(cast(document_records.c.id, String)).where(document_scope)
                )
            ]
            artifact_scope = predicates.get("documents.artifacts")
            if document_artifacts is not None and artifact_scope is not None:
                conditions.append(
                    cast(knowledge_documents.c.artifact_id, String).in_(
                        select(cast(document_artifacts.c.id, String)).where(artifact_scope)
                    )
                )
            predicates["knowledge.documents"] = or_(*conditions)

    runtime_executions = metadata.tables.get("runtime.executions")
    persistence_records = metadata.tables.get("runtime.persistence_records")
    execution_scope = predicates.get("runtime.executions")
    if runtime_executions is not None and persistence_records is not None and execution_scope is not None:
        predicates["runtime.persistence_records"] = persistence_records.c.execution_id.in_(
            select(cast(runtime_executions.c.id, String)).where(execution_scope)
        )

    changed = True
    while changed:
        changed = False
        for key, child in metadata.tables.items():
            if key in predicates or key == DELETION_EXECUTION_TABLE:
                continue
            for constraint in child.foreign_key_constraints:
                elements = list(constraint.elements)
                if len(elements) != 1:
                    continue
                element = elements[0]
                parent = element.column.table
                parent_key = parent.fullname
                parent_scope = predicates.get(parent_key)
                if parent_scope is None:
                    continue
                predicates[key] = element.parent.in_(select(element.column).where(parent_scope))
                changed = True
                break
    return predicates


def _count_table(db: Session, table: Table | None, predicate: Any | None) -> int:
    if table is None or predicate is None:
        return 0
    return int(db.scalar(select(func.count()).select_from(table).where(predicate)) or 0)


def _runtime_evidence_count(db: Session, metadata: MetaData, predicates: dict[str, Any]) -> int:
    return sum(
        _count_table(db, table, predicates.get(key))
        for key, table in metadata.tables.items()
        if key.startswith("runtime.") and ("evidence" in key or "acceptance" in key)
    )


def _resource_counts(
    db: Session,
    metadata: MetaData,
    predicates: dict[str, Any],
    external_objects: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resource, table_keys in PREVIEW_TABLES.items():
        if resource == "storage_objects":
            counts[resource] = len(external_objects)
            continue
        counts[resource] = sum(
            _count_table(db, metadata.tables.get(key), predicates.get(key)) for key in table_keys
        )
    counts["runtime_evidence"] = _runtime_evidence_count(db, metadata, predicates)
    return counts


def _external_object(
    bucket: str | None,
    key: str | None,
    origin: str,
    provider: str | None = None,
) -> dict[str, Any] | None:
    if not bucket or not key:
        return None
    provider_name = str(provider or "").strip().lower()
    if not provider_name:
        provider_name = "filesystem" if str(bucket).startswith("/") else "s3"
    return {
        "provider": provider_name,
        "bucket": str(bucket),
        "object_key": str(key),
        "origin": origin,
    }


def _external_objects(
    db: Session,
    metadata: MetaData,
    predicates: dict[str, Any],
    organization_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    objects: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, provider_column, bucket_column, object_column in (
        ("documents.document_versions", "object_store_provider", "object_store_bucket", "object_store_key"),
        ("documents.artifacts", "object_store_provider", "bucket", "object_key"),
    ):
        table = metadata.tables.get(key)
        predicate = predicates.get(key)
        if table is None or predicate is None or bucket_column not in table.c or object_column not in table.c:
            continue
        columns = [table.c[bucket_column], table.c[object_column]]
        has_provider = provider_column in table.c
        if has_provider:
            columns.insert(0, table.c[provider_column])
        rows = db.execute(select(*columns).where(predicate)).all()
        for row in rows:
            provider, bucket, object_key = row if has_provider else (None, *row)
            item = _external_object(bucket, object_key, key, provider)
            if item:
                objects[(item["provider"], item["bucket"], item["object_key"])] = item

    runtime_artifacts = metadata.tables.get("runtime.execution_artifacts")
    runtime_predicate = predicates.get("runtime.execution_artifacts")
    if runtime_artifacts is not None and runtime_predicate is not None and "storage_uri" in runtime_artifacts.c:
        for storage_uri in db.scalars(select(runtime_artifacts.c.storage_uri).where(runtime_predicate)):
            parsed = urlparse(str(storage_uri))
            if parsed.scheme == "s3" and parsed.netloc and parsed.path.lstrip("/"):
                item = _external_object(
                    parsed.netloc,
                    parsed.path.lstrip("/"),
                    "runtime.execution_artifacts",
                    "s3",
                )
                if item:
                    objects[(item["provider"], item["bucket"], item["object_key"])] = item

    return _inventory_external_objects(list(objects.values()), organization_id)


def _filesystem_inventory_blockers(item: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(str(item["bucket"])).resolve()
    binary = (root / str(item["object_key"])).resolve()
    try:
        binary.relative_to(root)
    except ValueError:
        return [
            {
                "code": "filesystem_object_key_escapes_storage_root",
                "message": "Filesystem object key escapes its persisted storage root.",
                "provider": "filesystem",
                "bucket": str(root),
                "object_key": str(item["object_key"]),
            }
        ]
    sidecar = binary.with_name(f"{binary.name}.metadata.json")
    blockers: list[dict[str, Any]] = []
    if not binary.is_file():
        blockers.append(
            {
                "code": "filesystem_object_binary_missing",
                "message": "Persisted filesystem object binary is missing.",
                "provider": "filesystem",
                "bucket": str(root),
                "object_key": str(item["object_key"]),
            }
        )
    if not sidecar.is_file():
        blockers.append(
            {
                "code": "filesystem_object_metadata_missing",
                "message": "Persisted filesystem object metadata sidecar is missing.",
                "provider": "filesystem",
                "bucket": str(root),
                "object_key": str(item["object_key"]),
            }
        )
    return blockers


def _remote_inventory_issue(
    *,
    code: str,
    message: str,
    provider: str,
    bucket: str,
    reason: str | None = None,
    object_key: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "provider": provider,
        "bucket": bucket,
        **({"object_key": object_key} if object_key else {}),
        **({"reason": reason} if reason else {}),
    }


def _inventory_remote_bucket(
    client: Any,
    objects: dict[tuple[str, str, str], dict[str, Any]],
    required: list[dict[str, Any]],
    organization_id: uuid.UUID,
    provider: str,
    bucket: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    try:
        for item in required:
            client.head_object(Bucket=bucket, Key=item["object_key"])
        continuation: str | None = None
        while True:
            params: dict[str, Any] = {"Bucket": bucket, "Prefix": f"{organization_id}/"}
            if continuation:
                params["ContinuationToken"] = continuation
            response = client.list_objects_v2(**params)
            for row in response.get("Contents") or []:
                item = _external_object(bucket, row.get("Key"), "organization_prefix", provider)
                if item:
                    objects[(provider, bucket, item["object_key"])] = item
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
    except ClientError as exc:
        status = int((exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        object_key = next((item["object_key"] for item in required), None)
        if status == 404 or code in {"NoSuchKey", "NotFound"}:
            blockers.append(
                _remote_inventory_issue(
                    code="object_storage_object_missing",
                    message="Persisted object storage object is missing.",
                    provider=provider,
                    bucket=bucket,
                    object_key=object_key,
                )
            )
        else:
            reason = type(exc).__name__
            warning = _remote_inventory_issue(
                code="object_storage_preview_unavailable",
                message="Required object storage inventory was unavailable.",
                provider=provider,
                bucket=bucket,
                reason=reason,
            )
            warnings.append(warning)
            blockers.append(
                _remote_inventory_issue(
                    code="object_storage_inventory_unavailable",
                    message="Required object storage inventory must succeed before governed deletion.",
                    provider=provider,
                    bucket=bucket,
                    reason=reason,
                )
            )
    except Exception as exc:
        reason = type(exc).__name__
        warnings.append(
            _remote_inventory_issue(
                code="object_storage_preview_unavailable",
                message="Required object storage inventory was unavailable.",
                provider=provider,
                bucket=bucket,
                reason=reason,
            )
        )
        blockers.append(
            _remote_inventory_issue(
                code="object_storage_inventory_unavailable",
                message="Required object storage inventory must succeed before governed deletion.",
                provider=provider,
                bucket=bucket,
                reason=reason,
            )
        )
    return warnings, blockers


def _inventory_external_objects(
    persisted_objects: list[dict[str, Any]],
    organization_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    objects = {
        (str(item["provider"]).lower(), str(item["bucket"]), str(item["object_key"])): dict(item)
        for item in persisted_objects
    }
    warnings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    remote_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in objects.values():
        provider = str(item["provider"]).lower()
        if provider == "filesystem":
            blockers.extend(_filesystem_inventory_blockers(item))
        elif provider in REMOTE_STORAGE_PROVIDERS:
            remote_groups.setdefault((provider, str(item["bucket"])), []).append(item)
        else:
            blockers.append(
                {
                    "code": "unsupported_object_storage_provider",
                    "message": "Persisted external object provider is unsupported.",
                    "provider": provider,
                    "bucket": str(item["bucket"]),
                    "object_key": str(item["object_key"]),
                }
            )
    if remote_groups:
        try:
            client = _s3_client()
        except Exception as exc:
            client = None
            reason = type(exc).__name__
            for provider, bucket in sorted(remote_groups):
                warnings.append(
                    _remote_inventory_issue(
                        code="object_storage_preview_unavailable",
                        message="Required object storage inventory was unavailable.",
                        provider=provider,
                        bucket=bucket,
                        reason=reason,
                    )
                )
                blockers.append(
                    _remote_inventory_issue(
                        code="object_storage_inventory_unavailable",
                        message="Required object storage inventory must succeed before governed deletion.",
                        provider=provider,
                        bucket=bucket,
                        reason=reason,
                    )
                )
        if client is not None:
            for (provider, bucket), required in sorted(remote_groups.items()):
                provider_warnings, provider_blockers = _inventory_remote_bucket(
                    client,
                    objects,
                    required,
                    organization_id,
                    provider,
                    bucket,
                )
                warnings.extend(provider_warnings)
                blockers.extend(provider_blockers)
    return (
        sorted(objects.values(), key=lambda item: (item["provider"], item["bucket"], item["object_key"])),
        warnings,
        blockers,
    )


def _s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        use_ssl=settings.object_storage_secure,
    )


def _execution_response(
    execution: OrganizationDeletionExecution,
    *,
    replayed: bool = False,
) -> OrganizationDeletionExecutionRead:
    counts = {str(key): int(value) for key, value in dict(execution.resource_counts_before or {}).items()}
    return OrganizationDeletionExecutionRead(
        deletion_execution_id=execution.id,
        organization_id=execution.organization_id,
        status=execution.status,
        requested_by=execution.requested_by,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        resource_counts_before=counts,
        resource_counts_deleted={
            str(key): int(value) for key, value in dict(execution.resource_counts_deleted or {}).items()
        },
        object_storage_objects_deleted=execution.object_storage_objects_deleted,
        blockers=list(execution.blockers or []),
        warnings=list(execution.warnings or []),
        failure_reason=execution.failure_reason,
        correlation_id=execution.correlation_id,
        external_objects=list(execution.external_objects or []),
        estimated_operations=sum(counts.values()) + len(execution.external_objects or []),
        replayed=replayed,
    )


def _find_execution(
    db: Session,
    organization_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> OrganizationDeletionExecution | None:
    statement = select(OrganizationDeletionExecution).where(
        OrganizationDeletionExecution.organization_id == organization_id
    )
    if idempotency_key is not None:
        statement = statement.where(OrganizationDeletionExecution.idempotency_key == idempotency_key)
    return db.scalar(statement.order_by(OrganizationDeletionExecution.created_at.desc()).limit(1))


def preview_organization_deletion(
    db: Session,
    organization: Organization,
    payload: OrganizationDeletionRequest,
    *,
    requested_by: str,
    correlation_id: str,
) -> OrganizationDeletionExecutionRead:
    request_hash = _request_hash(organization.id, requested_by)
    existing = _find_execution(db, organization.id, payload.idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("organization_deletion_idempotency_conflict")
        return _execution_response(existing, replayed=True)

    blockers = _validate_deletable(organization)
    execution = OrganizationDeletionExecution(
        organization_id=organization.id,
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        organization_name_hash=_stable_hash({"name": organization.name}),
        requested_by=requested_by,
        status="deletion_requested",
        correlation_id=correlation_id,
        blockers=blockers,
    )
    db.add(execution)
    db.flush()
    metadata = _reflect_metadata(db)
    predicates = _scope_predicates(metadata, organization.id)
    external_objects, warnings, storage_blockers = _external_objects(db, metadata, predicates, organization.id)
    counts = _resource_counts(db, metadata, predicates, external_objects)
    execution.resource_counts_before = counts
    execution.external_objects = external_objects
    execution.blockers = blockers + storage_blockers
    execution.warnings = warnings
    execution.status = "failed" if execution.blockers else "deletion_previewed"
    execution.failure_reason = "organization_deletion_blocked" if execution.blockers else None
    if not execution.blockers:
        organization.status = "deletion_previewed"
    db.add_all((execution, organization))
    db.flush()
    return _execution_response(execution)


def _delete_filesystem_object(storage_root: str, object_key: str) -> None:
    root = Path(storage_root).resolve()
    candidate = (root / object_key).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("filesystem_object_key_escapes_storage_root") from exc
    sidecar = candidate.with_name(f"{candidate.name}.metadata.json")
    candidate.unlink(missing_ok=True)
    sidecar.unlink(missing_ok=True)
    if candidate.exists() or sidecar.exists():
        raise RuntimeError("filesystem_object_delete_verification_failed")


def _delete_external_objects(objects: list[dict[str, Any]]) -> int:
    if not objects:
        return 0
    client = None
    deleted_count = 0
    for item in objects:
        provider = str(item.get("provider") or "s3").lower()
        bucket = str(item["bucket"])
        object_key = str(item["object_key"])
        if provider == "filesystem":
            _delete_filesystem_object(bucket, object_key)
            deleted_count += 1
            continue
        if provider not in {"s3", "minio", "object_storage"}:
            raise RuntimeError("unsupported_object_storage_provider")
        client = client or _s3_client()
        client.delete_object(Bucket=bucket, Key=object_key)
        try:
            client.head_object(Bucket=bucket, Key=object_key)
        except ClientError as exc:
            status = int((exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
            code = str((exc.response.get("Error") or {}).get("Code") or "")
            if status == 404 or code in {"NoSuchKey", "NotFound"}:
                deleted_count += 1
                continue
            raise
        raise RuntimeError("object_storage_delete_verification_failed")
    return deleted_count


def _delete_scoped_rows(
    db: Session,
    metadata: MetaData,
    predicates: dict[str, Any],
    organization_id: uuid.UUID,
    deletion_execution_id: uuid.UUID,
) -> dict[str, int]:
    deleted_counts: dict[str, int] = {}
    db.execute(
        text("SELECT set_config('app.organization_deletion_execution_id', :execution_id, true)"),
        {"execution_id": str(deletion_execution_id)},
    )
    processed: set[str] = set()
    for key in ("runtime.persistence_records", "knowledge.documents"):
        table = metadata.tables.get(key)
        predicate = predicates.get(key)
        if table is None or predicate is None:
            continue
        result = db.execute(delete(table).where(predicate))
        deleted_counts[key] = max(0, int(result.rowcount or 0))
        processed.add(key)
    for table in reversed(metadata.sorted_tables):
        key = table.fullname
        if key in processed or key in {DELETION_EXECUTION_TABLE, "core.organizations"}:
            continue
        predicate = predicates.get(key)
        if predicate is None:
            continue
        result = db.execute(delete(table).where(predicate))
        deleted_counts[key] = max(0, int(result.rowcount or 0))
    organization_table = metadata.tables["core.organizations"]
    result = db.execute(delete(organization_table).where(organization_table.c.id == organization_id))
    if int(result.rowcount or 0) != 1:
        raise RuntimeError("organization_delete_not_confirmed")
    deleted_counts["core.organizations"] = 1
    return deleted_counts


def delete_organization_governed(
    db: Session,
    organization_id: uuid.UUID,
    payload: OrganizationDeletionRequest,
    *,
    requested_by: str,
    correlation_id: str,
) -> OrganizationDeletionExecutionRead:
    execution = _find_execution(db, organization_id, payload.idempotency_key)
    if execution is None:
        raise ValueError("organization_deletion_preview_required")
    if execution.request_hash != _request_hash(organization_id, requested_by):
        raise ValueError("organization_deletion_idempotency_conflict")
    if execution.status == "deleted":
        return _execution_response(execution, replayed=True)
    if execution.status not in {"deletion_previewed", "failed"}:
        raise ValueError("organization_deletion_not_ready")
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise ValueError("organization_not_found")
    blockers = _validate_deletable(organization)
    if any(item.get("code") in STORAGE_PREVIEW_BLOCKER_CODES for item in execution.blockers or []):
        blockers = list(execution.blockers or [])
    if blockers:
        execution.status = "failed"
        execution.blockers = blockers
        execution.failure_reason = "organization_deletion_blocked"
        db.commit()
        return _execution_response(execution)

    execution.status = "deleting"
    execution.started_at = execution.started_at or _now()
    execution.correlation_id = correlation_id or execution.correlation_id
    organization.status = "deleting"
    db.add_all((execution, organization))
    db.commit()
    try:
        execution.object_storage_objects_deleted = _delete_external_objects(list(execution.external_objects or []))
        metadata = _reflect_metadata(db)
        predicates = _scope_predicates(metadata, organization_id)
        _delete_scoped_rows(db, metadata, predicates, organization_id, execution.id)
        deleted_resources = {
            str(resource): int(count)
            for resource, count in dict(execution.resource_counts_before or {}).items()
        }
        deleted_resources["storage_objects"] = execution.object_storage_objects_deleted
        execution.resource_counts_deleted = deleted_resources
        execution.status = "deleted"
        execution.completed_at = _now()
        execution.failure_reason = None
        db.add(execution)
        db.commit()
    except Exception as exc:
        db.rollback()
        execution = _find_execution(db, organization_id, payload.idempotency_key)
        if execution is None:
            raise
        execution.status = "failed"
        execution.failure_reason = type(exc).__name__
        execution.warnings = list(execution.warnings or []) + [
            {"code": "partial_deletion_failure", "message": "Organization deletion did not complete."}
        ]
        organization = db.get(Organization, organization_id)
        if organization is not None:
            organization.status = "failed"
            db.add(organization)
        db.add(execution)
        db.commit()
    return _execution_response(execution)


def get_organization_deletion_status(
    db: Session,
    organization_id: uuid.UUID,
) -> OrganizationDeletionExecutionRead | None:
    execution = _find_execution(db, organization_id)
    return _execution_response(execution) if execution is not None else None
