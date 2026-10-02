# Runtime Resilience Validation

## Purpose

This validation provides a bounded, reproducible baseline for API load, concurrent persistence and recovery after API restart.

It is not a destructive stress test and does not claim production capacity certification.

## Command

From the repository root:

```powershell
python scripts/validate_runtime_resilience.py
```

Default limits:

```text
200 requests per health endpoint
20 concurrent workers
25 temporary organization resources
1500 ms maximum p95 threshold
```

Custom bounded values:

```powershell
python scripts/validate_runtime_resilience.py `
  --requests 400 `
  --concurrency 25 `
  --resources 40 `
  --max-p95-ms 1500
```

## Validation flow

The script:

1. starts the fixed Compose platform;
2. verifies dependency health;
3. runs concurrent load against liveness;
4. runs concurrent load against readiness;
5. records throughput and latency percentiles;
6. creates and deletes temporary generic resources concurrently;
7. restarts only the API container;
8. verifies readiness recovery;
9. verifies dependency health after recovery;
10. shuts down the stack;
11. writes evidence.

## Non-AI contract

The validation disables embeddings, vector retrieval, object storage and enterprise extensions.

The core platform must remain healthy without those optional dependencies.

## Evidence

Results are written to:

```text
runtime/evidence/runtime-resilience.json
```

Important evidence fields:

```text
status
live_load.throughput_rps
live_load.latency_ms.p95
ready_load.throughput_rps
ready_load.latency_ms.p95
resource_cycle.created_resources
resource_cycle.deleted_resources
resource_cycle.failures
dependency_snapshot_before
dependency_snapshot_after
```

## Acceptance criteria

- zero failed liveness requests;
- zero failed readiness requests;
- p95 below the configured threshold;
- every temporary resource created and deleted;
- API readiness restored after restart;
- dependency health returns to healthy;
- clean shutdown completes.

## Interpretation

This result is a local pre-production baseline. Production sizing still requires environment-specific capacity, soak, failover and observability validation.
