# Platform Health Contracts

## Purpose

The platform separates process liveness, required dependency readiness, dependency inventory and operational platform health.

The contracts are:

```text
GET /health/live
GET /health/ready
GET /health/dependencies
GET /health/platform
```

## Liveness

```text
GET /health/live
```

Liveness confirms that the API process is running and can serve requests.

It does not validate PostgreSQL, schedulers, object storage, AI services or optional infrastructure.

Successful response:

```json
{
  "status": "ok"
}
```

## Readiness

```text
GET /health/ready
```

Readiness validates only dependencies required for the core platform to serve traffic.

Current required dependency:

- PostgreSQL.

Disabled optional services do not degrade readiness.

HTTP behavior:

- `200` when all required dependencies are healthy;
- `503` when any required dependency is unavailable.

## Dependency health

```text
GET /health/dependencies
```

This endpoint reports each dependency with:

- name;
- required/optional classification;
- enabled state;
- current configuration or availability state;
- diagnostic detail.

Supported states:

```text
alive
ready
degraded
unavailable
```

The compatibility `status` field remains available while `lifecycle_state`
provides the canonical runtime state.

The current dependency inventory includes:

- PostgreSQL — required;
- object storage — optional;
- embeddings — optional;
- vector retrieval — optional;
- AI provider execution — optional and disabled by policy.

An optional dependency that is disabled is reported as `alive` with compatibility
status `disabled` and does not produce readiness failure.

An optional dependency that is enabled but incomplete or temporarily unavailable
is `degraded` and does not block the core platform. Connectivity recovery is
detected without restarting the API.

## Platform health

```text
GET /health/platform
```

Platform health reports operational state beyond required infrastructure readiness, including scheduler activity and persistent platform workload state.

Scheduler health is based on persistent operational evidence:

- current worker status;
- current heartbeat;
- recent cycle start and completion timestamps;
- completed cycle count;
- degraded worker count;
- execution-capability assessment.

Relevant response fields include:

```text
latest_heartbeat_at
latest_cycle_started_at
latest_cycle_completed_at
scheduler_cycles_completed
scheduler_heartbeat_current
scheduler_loop_progressing
scheduler_execution_capable
```

A running process without a current heartbeat is not healthy.

A current heartbeat without recent loop completion is degraded.

A worker that persists `degraded` is degraded even if its process is still running.

Current statuses:

```text
healthy
degraded
critical
```

HTTP behavior:

- `200` for `healthy`;
- `200` for `degraded`, because the API and required dependencies remain available;
- `503` for `critical`.

A degraded scheduler state therefore remains observable without incorrectly declaring the entire API unavailable.

## Scheduler container healthcheck

The Compose scheduler container executes:

```text
python scheduler_healthcheck.py
```

The command queries the persistent scheduler-worker state associated with `SCHEDULER_OWNER_ID` and exits successfully only when:

- the worker record exists;
- status is `running`;
- heartbeat is within the configured threshold;
- a cycle completed within the configured threshold;
- at least one cycle has completed.

Configuration:

```text
SCHEDULER_HEALTH_HEARTBEAT_STALE_SECONDS
SCHEDULER_HEALTH_CYCLE_STALE_SECONDS
```

The healthcheck does not rely on PID existence.

## Architectural rule

The platform must remain functional without AI, embeddings, vector databases or object storage unless an administrator explicitly enables a capability that requires them.

Optional service absence is not a platform outage.

PostgreSQL remains the required source of truth and therefore participates in readiness.

Persistent scheduler, ingestion-worker and managed-service processes retry
transient PostgreSQL, Redis and object-storage failures with bounded backoff.
Non-transient implementation or configuration failures remain fail-fast.
