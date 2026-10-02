from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.artifact_publication import RuntimeArtifactPublication

PROTECTED_RETENTION_STATUSES = {
    "reserved",
    "publishing",
    "missing",
    "checksum_conflict",
    "reconciliation_required",
    "failed",
}


@dataclass(frozen=True)
class ArtifactRetentionPolicy:
    retain_for: timedelta
    remove_object: bool = False
    legal_hold: bool = False

    def __post_init__(self) -> None:
        if self.retain_for.total_seconds() < 0:
            raise ValueError("retain_for cannot be negative")


@dataclass(frozen=True)
class ArtifactRetentionDecision:
    eligible: bool
    reason: str
    due_at: datetime | None


class ArtifactRetentionPolicyService:
    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def evaluate(
        self,
        publication: RuntimeArtifactPublication,
        policy: ArtifactRetentionPolicy,
        *,
        now: datetime | None = None,
    ) -> ArtifactRetentionDecision:
        event_time = now or self._utcnow()
        if event_time.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if policy.legal_hold:
            return ArtifactRetentionDecision(False, "legal_hold", None)
        if publication.status in PROTECTED_RETENTION_STATUSES:
            return ArtifactRetentionDecision(False, "protected_status", None)
        if publication.status == "deleted":
            return ArtifactRetentionDecision(False, "already_deleted", None)
        due_at = publication.created_at + policy.retain_for
        if event_time < due_at:
            return ArtifactRetentionDecision(False, "not_due", due_at)
        return ArtifactRetentionDecision(True, "eligible", due_at)
