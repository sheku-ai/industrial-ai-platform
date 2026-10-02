class RuntimeLeaseLost(RuntimeError):
    """Signals that a worker no longer owns the execution lease.

    This exception is intentionally distinct from adapter failures. Callers must
    stop all durable mutations and must not attempt terminal transitions with the
    stale lease token. Recovery is owned by lease expiration and retry policy.
    """

    code = "runtime_lease_lost"
