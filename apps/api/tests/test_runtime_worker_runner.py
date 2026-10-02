from dataclasses import dataclass
from uuid import uuid4

from app.services.runtime_worker_runner import RuntimeWorkerRunner


@dataclass
class Health:
    stop_requested: bool = False


@dataclass
class CycleResult:
    outcome: str
    claimed: bool


class DaemonStub:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self._stop_requested = False

    def health(self):
        return Health(stop_requested=self._stop_requested)

    def run_cycle(self, organization_id, *, execution_type=None):
        self.calls.append((organization_id, execution_type))
        result = self.results.pop(0)
        if result.outcome == "stopped":
            self._stop_requested = True
        return result


def test_runner_counts_processed_and_idle_cycles():
    daemon = DaemonStub(
        [
            CycleResult("processed", True),
            CycleResult("idle", False),
        ]
    )
    sleeps = []
    runner = RuntimeWorkerRunner(
        daemon,
        poll_interval_seconds=0.25,
        sleeper=sleeps.append,
    )

    result = runner.run(uuid4(), execution_type="document.ingestion", max_cycles=2)

    assert result.cycles == 2
    assert result.processed == 1
    assert result.idle == 1
    assert result.stopped is False
    assert sleeps == [0.25]
    assert len(daemon.calls) == 2


def test_runner_stops_without_counting_stopped_cycle():
    daemon = DaemonStub([CycleResult("stopped", False)])
    runner = RuntimeWorkerRunner(daemon, poll_interval_seconds=0)

    result = runner.run(uuid4())

    assert result.cycles == 0
    assert result.processed == 0
    assert result.idle == 0
    assert result.stopped is True


def test_runner_does_not_sleep_after_processed_cycle():
    daemon = DaemonStub([CycleResult("processed", True)])
    sleeps = []
    runner = RuntimeWorkerRunner(daemon, poll_interval_seconds=1.0, sleeper=sleeps.append)

    result = runner.run(uuid4(), max_cycles=1)

    assert result.processed == 1
    assert sleeps == []
