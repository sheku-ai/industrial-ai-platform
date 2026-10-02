from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from app.models.documents import Chunk
from app.models.processing import ProcessingRevision


@dataclass(frozen=True)
class ProcessingRevisionSelection:
    requested_revision_id: UUID | None
    mode: str


def parse_processing_revision_selection(metadata: dict[str, Any]) -> tuple[ProcessingRevisionSelection, dict[str, Any]]:
    remaining = dict(metadata or {})
    raw_revision_id = remaining.pop("processing_revision_id", None)
    raw_mode = str(remaining.pop("processing_revision_mode", "latest_completed")).strip().lower()

    if raw_revision_id not in {None, ""}:
        try:
            revision_id = raw_revision_id if isinstance(raw_revision_id, UUID) else UUID(str(raw_revision_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("processing_revision_id must be a UUID") from exc
        return ProcessingRevisionSelection(revision_id, "explicit"), remaining

    if raw_mode not in {"latest_completed", "legacy_only"}:
        raise ValueError("processing_revision_mode must be latest_completed or legacy_only")
    return ProcessingRevisionSelection(None, raw_mode), remaining


def apply_processing_revision_selection(db_query, selection: ProcessingRevisionSelection, *, organization_id: UUID):
    if selection.mode == "legacy_only":
        return db_query.filter(Chunk.processing_revision_id.is_(None))

    if selection.mode == "explicit":
        completed_revision = select(ProcessingRevision.id).where(
            ProcessingRevision.id == selection.requested_revision_id,
            ProcessingRevision.organization_id == organization_id,
            ProcessingRevision.document_version_id == Chunk.document_version_id,
            ProcessingRevision.status == "completed",
        )
        return db_query.filter(
            Chunk.processing_revision_id == selection.requested_revision_id,
            completed_revision.exists(),
        )

    latest_revision = aliased(ProcessingRevision)
    latest_completed_revision_id = (
        select(latest_revision.id)
        .where(
            latest_revision.organization_id == organization_id,
            latest_revision.document_version_id == Chunk.document_version_id,
            latest_revision.status == "completed",
        )
        .order_by(latest_revision.completed_at.desc(), latest_revision.created_at.desc(), latest_revision.id.desc())
        .limit(1)
        .correlate(Chunk)
        .scalar_subquery()
    )
    return db_query.filter(
        or_(
            Chunk.processing_revision_id == latest_completed_revision_id,
            and_(
                Chunk.processing_revision_id.is_(None),
                latest_completed_revision_id.is_(None),
            ),
        )
    )


def candidate_revision_metadata(chunk: Chunk, selection: ProcessingRevisionSelection) -> dict[str, Any]:
    if chunk.processing_revision_id is None:
        mode = "legacy_fallback" if selection.mode == "latest_completed" else "legacy_only"
        selected_revision_id = None
    else:
        mode = selection.mode
        selected_revision_id = str(chunk.processing_revision_id)
    return {
        "processing_revision_id": selected_revision_id,
        "processing_revision_selection_mode": mode,
    }
