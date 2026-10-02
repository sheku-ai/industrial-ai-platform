from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from app.services.artifact_retention_policy import ArtifactRetentionPolicy, ArtifactRetentionPolicyService


@dataclass(frozen=True)
class ArtifactRetentionResult:
    outcome: str
    publication_id: UUID
    evidence_publication_id: UUID | None
    object_removed: bool


class ArtifactRetentionObjectStore(Protocol):
    def remove(self, storage_uri: str) -> bool: ...


class ArtifactRetentionAuditSink(Protocol):
    def record(
        self,
        *,
        organization_id: UUID,
        action: str,
        publication_id: UUID,
        outcome: str,
        occurred_at: datetime,
    ) -> None: ...


class ArtifactRetentionService:
    def __init__(
        self,
        lifecycle: ArtifactPublicationLifecycleService,
        object_store: ArtifactRetentionObjectStore,
        audit_sink: ArtifactRetentionAuditSink,
        policy_service: ArtifactRetentionPolicyService | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.object_store = object_store
        self.audit_sink = audit_sink
        self.policy_service = policy_service or ArtifactRetentionPolicyService()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def execute(
        self,
        organization_id: UUID,
        publication_id: UUID,
        policy: ArtifactRetentionPolicy,
        *,
        now: datetime | None = None,
    ) -> ArtifactRetentionResult:
        event_time = now or self._utcnow()
        publication = self.lifecycle.get(organization_id, publication_id, for_update=True)
        if publication is None:
            raise ValueError("artifact publication was not found")

        decision = self.policy_service.evaluate(publication, policy, now=event_time)
        if not decision.eligible:
            outcome = decision.reason
            self._audit(publication, outcome, event_time)
            return ArtifactRetentionResult(outcome, publication.id, None, False)

        removed = False
        if policy.remove_object:
            removed = self.object_store.remove(publication.storage_uri)
            if not removed:
                self._audit(publication, "remove_failed", event_time)
                return ArtifactRetentionResult("remove_failed", publication.id, None, False)

        evidence = self.lifecycle.reserve(
            organization_id=publication.organization_id,
            execution_id=publication.execution_id,
            artifact_id=publication.artifact_id,
            attempt_id=publication.attempt_id,
            storage_uri=publication.storage_uri,
            media_type=publication.media_type,
            checksum_sha256=publication.checksum_sha256,
            size_bytes=publication.size_bytes,
            metadata={
                "retention_of": str(publication.id),
                "object_removed": removed,
            },
        )
        status = "deleted" if removed else "retained"
        evidence = self.lifecycle.mark_terminal(
            publication.organization_id,
            evidence.id,
            status=status,
        )
        self._audit(publication, status, event_time)
        return ArtifactRetentionResult(status, publication.id, evidence.id, removed)

    def _audit(self, publication, outcome: str, occurred_at: datetime) -> None:
        self.audit_sink.record(
            organization_id=publication.organization_id,
            action="artifact.retention",
            publication_id=publication.id,
            outcome=outcome,
            occurred_at=occurred_at,
        )
