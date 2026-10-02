from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from app.models.segment_plan import IngestionSegment, IngestionSegmentPlan


@dataclass(frozen=True)
class SegmentCheckpointSummary:
    plan_id: UUID
    total_segments: int
    pending_segments: int
    processing_segments: int
    completed_segments: int
    failed_segments: int


class SegmentCheckpointRuntime:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def start_next(self, *, plan_id: UUID) -> IngestionSegment | None:
        session = self._session_factory()
        try:
            segment = session.scalar(
                select(IngestionSegment)
                .where(
                    IngestionSegment.plan_id == plan_id,
                    IngestionSegment.status.in_(("pending", "failed")),
                )
                .order_by(IngestionSegment.ordinal)
                .with_for_update(skip_locked=True)
            )
            if segment is None:
                session.rollback()
                return None
            now = datetime.now(UTC)
            segment.status = "processing"
            segment.attempt_count += 1
            segment.started_at = now
            segment.completed_at = None
            segment.updated_at = now
            plan = session.get(IngestionSegmentPlan, plan_id)
            if plan is not None and plan.status == "planned":
                plan.status = "processing"
                plan.updated_at = now
            session.commit()
            session.refresh(segment)
            session.expunge(segment)
            return segment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete(self, *, segment_id: UUID, checksum_sha256: str | None = None) -> SegmentCheckpointSummary:
        return self._finish(segment_id=segment_id, status="completed", checksum_sha256=checksum_sha256)

    def fail(self, *, segment_id: UUID) -> SegmentCheckpointSummary:
        return self._finish(segment_id=segment_id, status="failed", checksum_sha256=None)

    def summary(self, *, plan_id: UUID) -> SegmentCheckpointSummary:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(IngestionSegment.status, func.count())
                .where(IngestionSegment.plan_id == plan_id)
                .group_by(IngestionSegment.status)
            ).all()
            counts = {status: count for status, count in rows}
            return SegmentCheckpointSummary(
                plan_id=plan_id,
                total_segments=sum(counts.values()),
                pending_segments=counts.get("pending", 0),
                processing_segments=counts.get("processing", 0),
                completed_segments=counts.get("completed", 0),
                failed_segments=counts.get("failed", 0),
            )
        finally:
            session.close()

    def _finish(self, *, segment_id: UUID, status: str, checksum_sha256: str | None) -> SegmentCheckpointSummary:
        session = self._session_factory()
        try:
            segment = session.get(IngestionSegment, segment_id, with_for_update=True)
            if segment is None:
                raise ValueError("segment checkpoint does not exist")
            if segment.status == "completed" and status == "completed":
                plan_id = segment.plan_id
                session.rollback()
                return self.summary(plan_id=plan_id)
            if segment.status != "processing":
                raise ValueError(f"segment cannot transition from {segment.status} to {status}")
            now = datetime.now(UTC)
            segment.status = status
            segment.completed_at = now if status == "completed" else None
            segment.updated_at = now
            if checksum_sha256 is not None:
                segment.checksum_sha256 = checksum_sha256
            plan_id = segment.plan_id
            session.flush()
            remaining = session.scalar(
                select(func.count())
                .select_from(IngestionSegment)
                .where(
                    IngestionSegment.plan_id == plan_id,
                    IngestionSegment.status != "completed",
                )
            )
            plan = session.get(IngestionSegmentPlan, plan_id)
            if plan is not None:
                plan.status = "completed" if remaining == 0 else "processing"
                plan.updated_at = now
            session.commit()
            return self.summary(plan_id=plan_id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
