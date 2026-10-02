from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.artifact_reconciliation_batch import (
    ArtifactReconciliationBatchService,
    InvalidReconciliationCursor,
    InvalidReconciliationFilter,
    ReconciliationBatchItem,
    ReconciliationBatchLimitExceeded,
    ReconciliationCursor,
)


def _service(max_batch_limit: int = 100) -> ArtifactReconciliationBatchService:
    return ArtifactReconciliationBatchService(
        session_factory=lambda: None,
        object_store=object(),
        max_batch_limit=max_batch_limit,
    )


def test_cursor_round_trip_preserves_timestamp_and_publication_id() -> None:
    cursor = ReconciliationCursor(
        created_at=datetime(2026, 6, 20, 12, 30, tzinfo=UTC),
        publication_id=uuid4(),
    )

    decoded = ReconciliationCursor.decode(cursor.encode())

    assert decoded == cursor


def test_cursor_rejects_invalid_payload() -> None:
    with pytest.raises(InvalidReconciliationCursor):
        ReconciliationCursor.decode("not-a-valid-cursor")


def test_cursor_rejects_naive_timestamp() -> None:
    cursor = ReconciliationCursor(
        created_at=datetime(2026, 6, 20, 12, 30),
        publication_id=uuid4(),
    )

    with pytest.raises(InvalidReconciliationCursor):
        ReconciliationCursor.decode(cursor.encode())


def test_batch_limit_is_bounded() -> None:
    service = _service(max_batch_limit=25)

    with pytest.raises(ReconciliationBatchLimitExceeded):
        service._validate_filters(26, None)


def test_batch_rejects_unsupported_status_filter() -> None:
    service = _service()

    with pytest.raises(InvalidReconciliationFilter):
        service._validate_filters(10, ["deleted"])


def test_batch_deduplicates_status_filters() -> None:
    service = _service()

    statuses = service._validate_filters(10, ["published", "published", "missing"])

    assert statuses == ("published", "missing")


def test_batch_summary_counts_outcomes() -> None:
    first = uuid4()
    second = uuid4()
    third = uuid4()
    items = (
        ReconciliationBatchItem(first, uuid4(), "verified", True),
        ReconciliationBatchItem(second, second, "missing", False),
        ReconciliationBatchItem(
            third,
            None,
            "failed",
            False,
            error_code="unexpected_reconciliation_error",
        ),
    )

    result = ArtifactReconciliationBatchService._summarize(items, "next")

    assert result.scanned == 3
    assert result.processed == 2
    assert result.changed == 1
    assert result.verified == 1
    assert result.missing == 1
    assert result.checksum_conflict == 0
    assert result.unchanged == 1
    assert result.failed == 1
    assert result.next_cursor == "next"
