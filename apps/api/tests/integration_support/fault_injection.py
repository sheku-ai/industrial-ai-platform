from __future__ import annotations


class FaultInjectingHeartbeat:
    """Deterministic checkpoint fault injector for runtime boundary tests.

    The heartbeat raises the configured exception on an exact checkpoint number.
    It intentionally contains no timing, sleeps or production dependencies.
    """

    def __init__(self, *, fail_at: int | None = None, exception: Exception | None = None):
        self.fail_at = fail_at
        self.exception = exception
        self.checkpoint_count = 0

    def checkpoint(self):
        self.checkpoint_count += 1
        if self.fail_at == self.checkpoint_count:
            if self.exception is None:
                raise RuntimeError("fault injection requires an exception")
            raise self.exception
        return self.checkpoint_count
