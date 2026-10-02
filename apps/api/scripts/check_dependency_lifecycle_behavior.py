from __future__ import annotations

import json

from app.core.config import Settings
from app.services.dependency_health import build_readiness, evaluate_dependency_health
from app.services.runtime_dependency_recovery import RuntimeDependencyRecovery


class HealthySession:
    def execute(self, _statement):
        return object()

    def rollback(self) -> None:
        raise AssertionError("healthy session must not roll back")


def main() -> int:
    delays: list[float] = []
    recovery = RuntimeDependencyRecovery(
        initial_delay_seconds=0.25,
        maximum_delay_seconds=1.0,
        multiplier=2.0,
        sleep=delays.append,
    )
    observed_delays = [recovery.wait() for _ in range(4)]
    recovery.recovered()

    degraded = evaluate_dependency_health(
        HealthySession(),
        Settings(
            object_storage_endpoint_url="http://object-storage:9000",
            object_storage_bucket="runtime",
            secret_store_provider="redis",
            secret_store_redis_url="redis://redis:6379/0",
        ),
        object_storage_probe=lambda: False,
        redis_probe=lambda: True,
    )
    recovered = evaluate_dependency_health(
        HealthySession(),
        Settings(
            object_storage_endpoint_url="http://object-storage:9000",
            object_storage_bucket="runtime",
            secret_store_provider="redis",
            secret_store_redis_url="redis://redis:6379/0",
        ),
        object_storage_probe=lambda: True,
        redis_probe=lambda: True,
    )
    degraded_by_name = {item.name: item for item in degraded.dependencies}
    recovered_by_name = {item.name: item for item in recovered.dependencies}

    checks = {
        "backoff_deterministic": observed_delays == [0.25, 0.5, 1.0, 1.0],
        "backoff_sleep_used": delays == observed_delays,
        "backoff_resets": recovery.attempts == 0,
        "optional_outage_degraded": degraded.status == "degraded",
        "optional_outage_visible": (
            degraded_by_name["object_storage"].lifecycle_state == "degraded"
            and degraded_by_name["object_storage"].status == "unavailable"
        ),
        "core_remains_ready": build_readiness(degraded).status == "ready",
        "optional_dependency_recovers": (
            recovered.status == "healthy" and recovered_by_name["object_storage"].lifecycle_state == "ready"
        ),
        "redis_ready": recovered_by_name["redis_secret_store"].lifecycle_state == "ready",
        "ai_remains_optional": (
            recovered_by_name["ai_provider_execution"].required is False
            and recovered_by_name["ai_provider_execution"].status == "disabled"
        ),
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
