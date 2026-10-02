from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.runtime_lifecycle import RuntimeLifecycleService, RuntimeNotFoundError

DomainKind = Literal["document.ingestion", "document.indexing", "connector.run"]


class RuntimeCompatibilityError(RuntimeError):
    pass


class DomainJobNotFoundError(RuntimeCompatibilityError):
    pass


class DomainTenantMismatchError(RuntimeCompatibilityError):
    pass


@dataclass(frozen=True)
class DomainRuntimeLink:
    domain_kind: DomainKind
    domain_id: UUID
    organization_id: UUID
    runtime_execution_id: UUID
    created: bool


class RuntimeCompatibilityService:
    """Links domain-owned jobs to provider-neutral runtime executions.

    Domain status remains authoritative for the domain record. Runtime status remains
    authoritative for technical execution. This service never maps or overwrites
    either state implicitly.
    """

    def __init__(self, session: Session, *, enabled: bool = True) -> None:
        self.session = session
        self.enabled = enabled
        self.lifecycle = RuntimeLifecycleService(session)

    def link_ingestion_job(self, job_id: UUID) -> DomainRuntimeLink | None:
        if not self.enabled:
            return None
        row = (
            self.session.execute(
                text(
                    """
                SELECT id, organization_id, document_version_id, requested_by,
                       job_type, priority, runtime_execution_id
                FROM documents.ingestion_jobs
                WHERE id = :job_id
                FOR UPDATE
                """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DomainJobNotFoundError("ingestion job was not found")
        return self._create_and_link(
            domain_kind="document.ingestion",
            domain_id=row["id"],
            organization_id=row["organization_id"],
            existing_runtime_id=row["runtime_execution_id"],
            subject_type="documents.ingestion_job",
            subject_id=row["id"],
            requested_by=row["requested_by"],
            priority=row["priority"],
            input_payload={
                "job_type": row["job_type"],
                "document_version_id": str(row["document_version_id"]) if row["document_version_id"] else None,
            },
            update_statement="""
                UPDATE documents.ingestion_jobs
                SET runtime_execution_id = :runtime_execution_id
                WHERE id = :domain_id
                  AND organization_id = :organization_id
                  AND runtime_execution_id IS NULL
            """,
        )

    def link_indexing_job(self, job_id: UUID) -> DomainRuntimeLink | None:
        if not self.enabled:
            return None
        row = (
            self.session.execute(
                text(
                    """
                SELECT id, organization_id, document_version_id, index_target,
                       runtime_execution_id
                FROM documents.indexing_jobs
                WHERE id = :job_id
                FOR UPDATE
                """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DomainJobNotFoundError("indexing job was not found")
        return self._create_and_link(
            domain_kind="document.indexing",
            domain_id=row["id"],
            organization_id=row["organization_id"],
            existing_runtime_id=row["runtime_execution_id"],
            subject_type="documents.indexing_job",
            subject_id=row["id"],
            requested_by=None,
            priority=100,
            input_payload={
                "index_target": row["index_target"],
                "document_version_id": str(row["document_version_id"]) if row["document_version_id"] else None,
            },
            update_statement="""
                UPDATE documents.indexing_jobs
                SET runtime_execution_id = :runtime_execution_id
                WHERE id = :domain_id
                  AND organization_id = :organization_id
                  AND runtime_execution_id IS NULL
            """,
        )

    def link_connector_run(self, run_id: UUID) -> DomainRuntimeLink | None:
        if not self.enabled:
            return None
        row = (
            self.session.execute(
                text(
                    """
                SELECT cr.id, cr.runtime_execution_id, c.organization_id,
                       cr.connector_id
                FROM connectors.connector_runs cr
                JOIN connectors.connectors c ON c.id = cr.connector_id
                WHERE cr.id = :run_id
                FOR UPDATE OF cr
                """
                ),
                {"run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DomainJobNotFoundError("connector run was not found")
        if row["organization_id"] is None:
            raise DomainTenantMismatchError("connector run requires a tenant-owned connector")
        return self._create_and_link(
            domain_kind="connector.run",
            domain_id=row["id"],
            organization_id=row["organization_id"],
            existing_runtime_id=row["runtime_execution_id"],
            subject_type="connectors.connector_run",
            subject_id=row["id"],
            requested_by=None,
            priority=100,
            input_payload={"connector_id": str(row["connector_id"])},
            update_statement="""
                UPDATE connectors.connector_runs
                SET runtime_execution_id = :runtime_execution_id
                WHERE id = :domain_id
                  AND runtime_execution_id IS NULL
            """,
        )

    def _create_and_link(
        self,
        *,
        domain_kind: DomainKind,
        domain_id: UUID,
        organization_id: UUID,
        existing_runtime_id: UUID | None,
        subject_type: str,
        subject_id: UUID,
        requested_by: str | None,
        priority: int,
        input_payload: dict[str, Any],
        update_statement: str,
    ) -> DomainRuntimeLink:
        if existing_runtime_id is not None:
            execution = self.lifecycle.executions.get(organization_id, existing_runtime_id)
            if execution is None:
                raise RuntimeNotFoundError("linked runtime execution was not found in tenant scope")
            return DomainRuntimeLink(domain_kind, domain_id, organization_id, execution.id, False)

        execution, created = self.lifecycle.create_or_get(
            organization_id=organization_id,
            execution_type=domain_kind,
            subject_type=subject_type,
            subject_id=subject_id,
            idempotency_key=f"{domain_kind}:{domain_id}",
            requested_by=requested_by,
            priority=priority,
            input_payload=input_payload,
        )
        self.session.execute(
            text(update_statement),
            {
                "runtime_execution_id": execution.id,
                "domain_id": domain_id,
                "organization_id": organization_id,
            },
        )
        self.session.flush()
        return DomainRuntimeLink(domain_kind, domain_id, organization_id, execution.id, created)
