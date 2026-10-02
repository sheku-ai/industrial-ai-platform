from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.models.segment_plan import IngestionSegment, IngestionSegmentPlan


class SegmentPlanRuntime:
    def __init__(
        self,
        session_factory,
        *,
        heavy_segment_bytes: int = 50_000_000,
        pdf_pages_per_segment: int = 100,
    ) -> None:
        if heavy_segment_bytes <= 0:
            raise ValueError("heavy_segment_bytes must be positive")
        if pdf_pages_per_segment <= 0:
            raise ValueError("pdf_pages_per_segment must be positive")
        self._session_factory = session_factory
        self._heavy_segment_bytes = heavy_segment_bytes
        self._pdf_pages_per_segment = pdf_pages_per_segment

    def ensure_plan(
        self,
        *,
        organization_id,
        execution_id,
        document_version_id,
        source_checksum_sha256: str,
        content_length: int,
        execution_class: str,
        detected_media_type: str,
        page_count_hint: int | None = None,
        pages_per_segment: int | None = None,
    ) -> tuple[str, int, str]:
        if content_length <= 0:
            raise ValueError("segment planning requires a non-empty source")
        if pages_per_segment is not None and pages_per_segment <= 0:
            raise ValueError("pages_per_segment must be positive")

        session = self._session_factory()
        try:
            existing = session.scalar(
                select(IngestionSegmentPlan).where(
                    IngestionSegmentPlan.organization_id == organization_id,
                    IngestionSegmentPlan.execution_id == execution_id,
                )
            )
            if existing is not None:
                return str(existing.id), existing.segment_count, existing.strategy

            use_pdf_pages = (
                detected_media_type == "application/pdf" and page_count_hint is not None and page_count_hint > 0
            )
            if use_pdf_pages:
                strategy = "pdf_page_range"
                segment_size = pages_per_segment or self._pdf_pages_per_segment
                segment_count = max(1, math.ceil(page_count_hint / segment_size))
                configuration_snapshot = {
                    "range_unit": "page",
                    "pages_per_segment": segment_size,
                    "page_count": page_count_hint,
                }
            else:
                segment_size = content_length if execution_class == "normal" else self._heavy_segment_bytes
                segment_count = max(1, math.ceil(content_length / segment_size))
                strategy = "single" if segment_count == 1 else "byte_range"
                configuration_snapshot = {
                    "range_unit": "byte",
                    "segment_size_bytes": segment_size,
                }

            now = datetime.now(UTC)
            plan = IngestionSegmentPlan(
                id=uuid4(),
                organization_id=organization_id,
                execution_id=execution_id,
                document_version_id=document_version_id,
                source_checksum_sha256=source_checksum_sha256,
                strategy=strategy,
                execution_class=execution_class,
                status="planned",
                segment_count=segment_count,
                configuration_snapshot=configuration_snapshot,
                created_at=now,
                updated_at=now,
            )
            session.add(plan)
            session.flush()

            for ordinal in range(segment_count):
                start = ordinal * segment_size
                if use_pdf_pages:
                    end = min(page_count_hint, start + segment_size)
                    metadata = {
                        "range_unit": "page",
                        "page_start": start,
                        "page_end_exclusive": end,
                    }
                else:
                    end = min(content_length, start + segment_size)
                    metadata = {"range_unit": "byte"}
                session.add(
                    IngestionSegment(
                        id=uuid4(),
                        plan_id=plan.id,
                        ordinal=ordinal,
                        segment_key=f"segment-{ordinal:06d}",
                        range_start=start,
                        range_end_exclusive=end,
                        status="pending",
                        attempt_count=0,
                        metadata_=metadata,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.commit()
            return str(plan.id), segment_count, strategy
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
