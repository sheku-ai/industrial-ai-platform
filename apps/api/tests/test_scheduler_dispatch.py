import pytest

from app.services.scheduler_dispatch import SchedulerDispatchService


def test_forbid_overlap_only_allows_empty_runtime() -> None:
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="forbid_overlap",
        active_count=0,
        max_concurrent_runs=1,
    ) is True
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="forbid_overlap",
        active_count=1,
        max_concurrent_runs=1,
    ) is False


def test_allow_bounded_respects_configured_limit() -> None:
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="allow_bounded",
        active_count=1,
        max_concurrent_runs=2,
    ) is True
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="allow_bounded",
        active_count=2,
        max_concurrent_runs=2,
    ) is False


def test_replace_pending_respects_running_execution_limit() -> None:
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="replace_pending",
        active_count=0,
        max_concurrent_runs=1,
    ) is True
    assert SchedulerDispatchService.concurrency_allows_dispatch(
        policy="replace_pending",
        active_count=1,
        max_concurrent_runs=1,
    ) is False


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported concurrency policy"):
        SchedulerDispatchService.concurrency_allows_dispatch(
            policy="unknown",
            active_count=0,
            max_concurrent_runs=1,
        )
