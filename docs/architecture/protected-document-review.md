# Protected Document Review

## Status

```text
Sprint: 25.6A
Stage: PRE-PRODUCTION
Automatic password guessing: PROHIBITED
Human review: REQUIRED FOR PROTECTED CONTENT
```

## Decision

Password-protected or encrypted documents are not discarded and are not classified as ordinary extraction failures.

They are registered, preserved and moved into a controlled human-review workflow.

```text
protected document detected
  -> preserve original payload
  -> stop provider fallback
  -> create review case
  -> pending_human_review
  -> authorized human decision
  -> controlled retry, metadata-only approval, rejection or quarantine
```

## Review reasons

```text
password_required
encrypted_document
encrypted_container
unsupported_encryption
corrupted_or_encrypted
malware_scan_required
manual_classification_required
```

## Review states

```text
pending_human_review
credentials_supplied
approved_for_processing
approved_metadata_only
rejected_by_reviewer
quarantined
expired
resolved
```

These states are distinct from ingestion `failed`. A protected file may be valid and recoverable.

## Allowed reviewer actions

```text
provide_password
approve_metadata_only
approve_external_decryption
request_new_copy
reject_document
quarantine
```

Actions are policy-controlled and auditable. The platform must not assume a fixed business role; permissions are assigned through the configurable security model.

## Secret handling

Passwords and decryption keys:

- must never be stored in document metadata;
- must never appear in logs, audit payloads or error messages;
- must be stored only through a secret-store reference;
- must be scoped to the review case or processing attempt;
- should be single-use by default;
- must expire;
- must be destroyed or revoked after processing;
- must not be reused across documents;
- must not be sent to cloud providers unless explicitly authorized by policy.

The application contract stores only a `TemporarySecretReference`, never the plaintext secret.

## Provider behavior

When a provider detects encryption or password protection it returns a controlled result containing:

```text
error_code: password_required | encrypted_document | encrypted_container
review_required: true
protected_document: true
```

The rich-document adapter immediately stops fallback processing. This prevents multiple providers from attempting the same protected payload and preserves the original detection reason.

## PDF behavior

The native PDF provider inspects the PDF encryption flag before page extraction. An encrypted PDF returns:

```text
status: partial
error_code: password_required
review_required: true
```

The subsequent runtime layer must create a `DocumentReviewCase` and move the ingestion job to a review-waiting state.

## Container behavior

Encrypted ZIP, TAR-compatible wrappers or other protected containers must follow the same review workflow before expansion. No brute-force attempts are allowed.

After an authorized secret is supplied:

```text
secret reference resolved inside isolated worker
  -> container opened in sandbox
  -> entries validated independently
  -> source secret revoked
  -> extracted entries routed normally
```

## Audit requirements

Audit records must include:

- review case identifier;
- document-version identifier;
- reason and detected format;
- provider that detected protection;
- state transitions;
- reviewer subject;
- selected action;
- timestamps;
- processing outcome;
- secret reference lifecycle events without secret value.

## Current implementation boundary

Implemented in 25.6A:

- review reasons, states and actions;
- transition validation;
- review-case creation;
- temporary secret-reference contract;
- PDF encryption detection;
- rich-document fallback stop;
- unit tests for review and secret rules.

Not yet implemented:

- PostgreSQL tables and Alembic migration;
- review API endpoints;
- administrative review UI;
- concrete secret-store adapter;
- password-enabled retry worker;
- encrypted ZIP detection;
- expiry scheduler;
- notification delivery.

Those are the remaining implementation slices of the protected-document workflow.
