import pytest

from app.services.scheduler_runtime_sync import SchedulerRuntimeSyncService


def test_runtime_success_maps_to_scheduler_success() -> None:
    assert SchedulerRuntimeSyncService.map_status("succeeded") == "succeeded"


def test_runtime_cancel_maps_to_scheduler_cancel() -> None:
    assert SchedulerRuntimeSyncService.map_status("cancelled") == "cancelled"


@pytest.mark.parametrize("runtime_status", ["failed", "dead_lettered"])
def test_runtime_failure_states_map_to_scheduler_failure(runtime_status: str) -> None:
    assert SchedulerRuntimeSyncService.map_status(runtime_status) == "failed"


def test_non_terminal_runtime_state_is_rejected() -> None:
    with pytest.raises(ValueError, match="not terminal"):
        SchedulerRuntimeSyncService.map_status("running")
