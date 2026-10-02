# Protected Document Review Runtime

## Status

```text
Sprint: 25.6A.3
Stage: PRE-PRODUCTION
Plaintext secret persistence: PROHIBITED
Automatic password guessing: PROHIBITED
```

## Objective

Complete the runtime boundary between human review and an authorized ingestion retry without persisting password values in PostgreSQL.

## Secret-store contract

The platform defines a provider-neutral `SecretStore` contract:

```text
put(reference, secret)
inspect(reference)
resolve(reference)
revoke(reference)
```

`inspect` validates existence and expiry without consuming a single-use secret.

`resolve` is reserved for the isolated worker that actually opens the protected document. A single-use secret is removed when resolved.

`revoke` is idempotent and is used after completion, expiry, rejection or quarantine.

## Local implementation

`InMemorySecretStore` is provided only for tests and local development.

It:

- keeps values in process memory;
- never writes secret values to PostgreSQL;
- supports expiry;
- supports single-use resolution;
- supports explicit revocation.

It is not suitable for distributed or production deployment. Production must bind the same contract to an external secret manager.

## Authorized retry

```text
credentials_supplied
  -> validate review transition
  -> inspect secret reference
  -> create new runtime execution
  -> approved_for_processing
  -> worker resolves secret once
  -> processing completes
  -> secret revoked or consumed
```

The retry execution contains only:

- document identifiers;
- source reference;
- review-case identifier;
- secret reference;
- secret expiry metadata;
- previous execution reference.

The secret value is never placed in:

- runtime input payload;
- policy snapshot;
- review events;
- logs;
- document metadata;
- audit details.

## Runtime execution

An authorized retry creates a new `runtime.executions` row with:

```text
execution_type: document.ingestion
subject_type: document_version
status: pending
priority: 50
correlation_id: document-review:<review_id>
```

A new execution is preferred over mutating a completed or failed historical execution. This preserves the execution history and retry provenance.

## Expiry

Due review cases in active review states are moved to `expired`.

Expiry processing:

- revokes the secret reference;
- clears secret-reference metadata from the review case;
- records `resolved_at`;
- creates a `review_expired` event;
- does not delete the original document payload.

## API

```text
POST /api/document-reviews/{review_id}/retry
POST /api/document-reviews/expire-due
```

The retry endpoint requires an actor subject and returns the new runtime execution identifier.

The expiry endpoint is an operational baseline. It should later be invoked by the configurable scheduler rather than manually.

## Remaining implementation

- external secret-manager adapters;
- worker-side secret resolution and guaranteed revocation;
- scheduler registration for expiry;
- authorization policies for review actions;
- administrative portal queue;
- completion callback that resolves or reopens the review case;
- integration tests against PostgreSQL and a concrete secret provider.
