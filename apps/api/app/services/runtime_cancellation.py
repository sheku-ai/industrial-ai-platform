class RuntimeCancellationRequested(RuntimeError):
    """Raised by adapters when a cooperative cancellation request is observed."""

    code = "runtime_cancellation_requested"
