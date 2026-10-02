from datetime import UTC, datetime

import pytest

from app.services.scheduler_evaluation import (
    SchedulerConfigurationError,
    SchedulerEvaluationService,
)


def test_next_occurrence_uses_utc() -> None:
    after = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)

    result = SchedulerEvaluationService.next_occurrence("*/15 * * * *", "UTC", after)

    assert result == datetime(2026, 6, 21, 12, 15, tzinfo=UTC)


def test_next_occurrence_converts_local_timezone_to_utc() -> None:
    after = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)

    result = SchedulerEvaluationService.next_occurrence("0 9 * * *", "America/Santiago", after)

    assert result.tzinfo == UTC
    assert result > after


def test_invalid_cron_expression_is_rejected() -> None:
    with pytest.raises(SchedulerConfigurationError, match="invalid cron expression"):
        SchedulerEvaluationService.next_occurrence("not-a-cron", "UTC", datetime.now(UTC))


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(SchedulerConfigurationError, match="unknown timezone"):
        SchedulerEvaluationService.next_occurrence("0 * * * *", "Invalid/Timezone", datetime.now(UTC))
