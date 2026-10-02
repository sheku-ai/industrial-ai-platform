from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.artifact_publication import RuntimeArtifactPublication
from app.services.artifact_publication_lifecycle import ArtifactPublicationLifecycleService
from app.services.artifact_reconciliation import ArtifactObjectStore, ArtifactReconciliationService

DEFAULT_CANDIDATE_STATUSES = (
    "reserved",
    "publishing",
    "published",
    "missing",
    "checksum_conflict",
)
MAX_BATCH_LIMIT = 100


class ArtifactReconciliationBatchError(RuntimeError):
    code = "artifact_reconciliation_batch_error"


class InvalidReconciliationCursor(ArtifactReconciliationBatchError):
    code = "invalid_cursor"


class InvalidReconciliationFilter(ArtifactReconciliationBatchError):
    code = "invalid_filter"


class ReconciliationBatchLimitExceeded(ArtifactReconciliationBatchError):
    code = "batch_limit_exceeded"


@dataclass(frozen=True)
class ReconciliationCursor:
    created_at: datetime
    publication_id: UUID

    def encode(self) -> str:
        payload = {
            "created_at": self.created_at.isoformat(),
            "publication_id": str(self.publication_id),
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, value: str) -> ReconciliationCursor:
        try:
            padding = "=" * (-len(value) % 4)
            payload = json.loads(urlsafe_b64decode(value + padding).decode("utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            publication_id = UUID(payload["publication_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidReconciliationCursor("invalid reconciliation cursor") from exc
        if created_at.tzinfo is None:
            raise InvalidReconciliationCursor("cursor timestamp must be timezone-aware")
        return cls(created_at=created_at, publication_id=publication_id)


@dataclass(frozen=True)
class ReconciliationCandidate:
    publication_id: UUID
    artifact_id: UUID
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ReconciliationBatchItem:
    source_publication_id: UUID
    resulting_publication_id: UUID | None
    outcome: str
    changed: bool
    error_code: str | None = None


@dataclass(frozen=True)
class ReconciliationBatchResult:
    scanned: int
    processed: int
    changed: int
    verified: int
    missing: int
    checksum_conflict: int
    unchanged: int
    failed: int
    next_cursor: str | None
    items: tuple[ReconciliationBatchItem, ...]


class ArtifactReconciliationCandidateRepository:
    """Tenant-scoped query for only the latest publication of each artifact."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_latest_candidates(
        self,
        organization_id: UUID,
        *,
        limit: int,
        statuses: Sequence[str],
        cursor: ReconciliationCursor | None = None,
    ) -> list[ReconciliationCandidate]:
        latest = (
            select(
                RuntimeArtifactPublication.artifact_id.label("artifact_id"),
                func.max(RuntimeArtifactPublication.publication_number).label("publication_number"),
            )
            .where(RuntimeArtifactPublication.organization_id == organization_id)
            .group_by(RuntimeArtifactPublication.artifact_id)
            .subquery()
        )

        statement = (
            select(RuntimeArtifactPublication)
            .join(
                latest,
                and_(
                    RuntimeArtifactPublication.artifact_id == latest.c.artifact_id,
                    RuntimeArtifactPublication.publication_number == latest.c.publication_number,
                ),
            )
            .where(
                RuntimeArtifactPublication.organization_id == organization_id,
                RuntimeArtifactPublication.status.in_(tuple(statuses)),
            )
            .order_by(
                RuntimeArtifactPublication.created_at,
                RuntimeArtifactPublication.id,
            )
            .limit(limit + 1)
        )

        if cursor is not None:
            statement = statement.where(
                or_(
                    RuntimeArtifactPublication.created_at > cursor.created_at,
                    and_(
                        RuntimeArtifactPublication.created_at == cursor.created_at,
                        RuntimeArtifactPublication.id > cursor.publication_id,
                    ),
                )
            )

        publications = list(self.session.scalars(statement))
        return [
            ReconciliationCandidate(
                publication_id=publication.id,
                artifact_id=publication.artifact_id,
                status=publication.status,
                created_at=publication.created_at,
            )
            for publication in publications
        ]


class ArtifactReconciliationBatchService:
    """Coordinate bounded reconciliation with one transaction per publication."""

    def __init__(
        self,
        session_factory,
        object_store: ArtifactObjectStore,
        *,
        max_batch_limit: int = MAX_BATCH_LIMIT,
    ) -> None:
        self.session_factory = session_factory
        self.object_store = object_store
        self.max_batch_limit = max_batch_limit

    def run(
        self,
        organization_id: UUID,
        *,
        limit: int,
        statuses: Iterable[str] | None = None,
        cursor: str | None = None,
        dry_run: bool = False,
    ) -> ReconciliationBatchResult:
        normalized_statuses = self._validate_filters(limit, statuses)
        decoded_cursor = ReconciliationCursor.decode(cursor) if cursor else None

        listing_session = self.session_factory()
        try:
            candidates = ArtifactReconciliationCandidateRepository(listing_session).list_latest_candidates(
                organization_id,
                limit=limit,
                statuses=normalized_statuses,
                cursor=decoded_cursor,
            )
        finally:
            listing_session.close()

        has_more = len(candidates) > limit
        selected = candidates[:limit]
        items: list[ReconciliationBatchItem] = []

        for candidate in selected:
            session = self.session_factory()
            try:
                lifecycle = ArtifactPublicationLifecycleService(session)
                service = ArtifactReconciliationService(lifecycle, self.object_store)
                if dry_run:
                    preview = service.preview(organization_id, candidate.publication_id)
                    item = ReconciliationBatchItem(
                        source_publication_id=preview.source_publication_id,
                        resulting_publication_id=None,
                        outcome=preview.outcome,
                        changed=preview.would_change,
                    )
                    session.rollback()
                else:
                    result = service.reconcile(organization_id, candidate.publication_id)
                    session.commit()
                    item = ReconciliationBatchItem(
                        source_publication_id=result.source_publication_id,
                        resulting_publication_id=result.resulting_publication_id,
                        outcome=result.outcome,
                        changed=result.changed,
                    )
            except Exception:
                session.rollback()
                item = ReconciliationBatchItem(
                    source_publication_id=candidate.publication_id,
                    resulting_publication_id=None,
                    outcome="failed",
                    changed=False,
                    error_code="unexpected_reconciliation_error",
                )
            finally:
                session.close()
            items.append(item)

        next_cursor = None
        if has_more and selected:
            last = selected[-1]
            next_cursor = ReconciliationCursor(last.created_at, last.publication_id).encode()

        return self._summarize(items, next_cursor)

    def _validate_filters(
        self,
        limit: int,
        statuses: Iterable[str] | None,
    ) -> tuple[str, ...]:
        if limit < 1 or limit > self.max_batch_limit:
            raise ReconciliationBatchLimitExceeded(f"limit must be between 1 and {self.max_batch_limit}")
        normalized = tuple(dict.fromkeys(statuses or DEFAULT_CANDIDATE_STATUSES))
        unsupported = set(normalized) - set(DEFAULT_CANDIDATE_STATUSES)
        if unsupported:
            raise InvalidReconciliationFilter("unsupported reconciliation status filter")
        return normalized

    @staticmethod
    def _summarize(
        items: Sequence[ReconciliationBatchItem],
        next_cursor: str | None,
    ) -> ReconciliationBatchResult:
        changed = sum(1 for item in items if item.changed)
        failed = sum(1 for item in items if item.outcome == "failed")
        return ReconciliationBatchResult(
            scanned=len(items),
            processed=len(items) - failed,
            changed=changed,
            verified=sum(1 for item in items if item.outcome == "verified"),
            missing=sum(1 for item in items if item.outcome == "missing"),
            checksum_conflict=sum(1 for item in items if item.outcome == "checksum_conflict"),
            unchanged=sum(1 for item in items if not item.changed and item.outcome != "failed"),
            failed=failed,
            next_cursor=next_cursor,
            items=tuple(items),
        )
