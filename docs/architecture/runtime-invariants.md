# Runtime Invariants

## Status

```text
runtime_model = APPROVED
migration_contract = APPROVED_FOR_IMPLEMENTATION_AFTER_19.0
provider_execution = DISABLED
```

This document contains only durable runtime rules. Implementation details, migration object names and sprint tasks belong in their respective documents.

## Tenancy

- Every execution, attempt, event and runtime artifact has exactly one non-null `organization_id`.
- Child runtime rows must match the organization of their parent execution.
- Events and artifacts that reference an attempt must match both the execution and organization of that attempt.
- Tenant consistency is enforced by composite database constraints, not only by application filtering.
- Cross-organization access is rejected before repository access.
- Global runtime executions are not supported.

## Ownership and Transactions

- Domain records describe business requests and results.
- Runtime records describe durable technical execution.
- Application services own transaction boundaries.
- Repositories never commit or rollback independently.
- Workers use tenant-scoped repositories and lifecycle services.
- Provider adapters never write directly to PostgreSQL.
- Lifecycle mutation and its corresponding event commit atomically.

## Executions

- An execution is the canonical durable record for one asynchronous technical operation.
- Reprocessing creates a new execution and requires a new idempotency key.
- Terminal executions cannot return to active states.
- Cancellation request and cancellation completion are distinct.
- Successful executions contain no active error.
- Failed, expired and dead-lettered conditions require a sanitized reason.
- Terminal execution states require `finished_at`.

## Attempts and Leases

- Attempt numbers are unique and strictly increasing per execution.
- Retry creates a new attempt and preserves previous attempts.
- At most one attempt may hold an active lease for an execution.
- An active lease requires worker identity, lease token, lease time and expiry.
- Lease expiry must be later than lease acquisition.
- Only the current non-expired lease token may heartbeat, start, complete, fail, abandon or release work.
- Closed attempts are immutable.
- Active attempts may change only through authorized lifecycle transitions and heartbeat updates.
- Attempt completion never overwrites or reuses previous attempt history.

## Time

- `available_at` cannot precede `requested_at`.
- `started_at` cannot precede `requested_at`.
- `finished_at` cannot precede `started_at` when both exist.
- Lease expiry cannot precede or equal lease acquisition.
- Accepted heartbeats cannot precede lease acquisition.
- All persisted timestamps use timezone-aware UTC values.

## Events

- Runtime events are append-only.
- Event sequence numbers are unique and monotonically increasing per execution.
- Sequence numbers do not need to be gapless.
- Sequence allocation occurs inside the lifecycle transaction while the execution is locked.
- Events cannot be updated or deleted independently.
- Aggregate retention may remove events only through controlled execution purge.

## Idempotency

- Idempotency scope is `organization_id`, `execution_type` and `idempotency_key`.
- Repeated requests return the canonical execution while that execution remains retained.
- An idempotency key cannot be reused while its execution exists.
- Reprocessing requires a new key and a new execution.
- Provider request identifiers are opaque references and are not platform idempotency keys.
- Concurrent creation attempts must converge on one canonical execution.

## Security

- Runtime records never contain credentials, tokens, connection strings or raw secrets.
- Lease tokens are runtime ownership tokens, not provider credentials.
- Provider references are opaque sanitized metadata.
- Persisted errors are sanitized before storage.
- Administrative retry, cancellation, dead-letter and purge actions are audited.

## Domain Compatibility

- `documents.ingestion_jobs`, `documents.indexing_jobs` and `connectors.connector_runs` remain domain-owned records.
- Runtime does not replace, rename or silently repurpose domain job tables.
- Domain/runtime synchronization is performed by application services, not cross-schema triggers.
- Runtime remains provider-neutral and independent of AI, embeddings and vector databases.
