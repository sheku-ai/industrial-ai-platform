# SHEKU — Production Readiness

Repository: `sheku-ai/industrial-ai-platform`  
Release line: `1.6.0` (pre-production Release Candidate)

## Purpose

This document defines the evidence required to classify a SHEKU release as production-ready.

Functional success, local execution and a passing development quality gate do not by themselves prove production readiness.

For the ordered installation, Quality Gate, Product Acceptance and RC packaging commands, see the [Release Candidate validation workflow](../installation/local-runtime.md#release-candidate-validation). RC eligibility is distinct from production readiness.

## Readiness principle

Production readiness is evidence-driven and fail-closed.

```text
functional validation
+ security validation
+ recovery validation
+ deployment validation
+ capacity validation
+ observability validation
+ migration validation
+ release evidence
= production readiness
```

No convenience flag, successful UI journey or external-service response can substitute for the required persisted evidence.

## Authoritative boundaries

SHEKU uses separate persistence authorities:

```text
Platform PostgreSQL
= product configuration
+ organization/domain ownership
+ lifecycle state
+ governed knowledge
+ runtime evidence

Identity PostgreSQL
= identities
+ authentication state
+ governed sessions
+ identity-domain audit

Object storage
= source binaries
+ derived binary artifacts
```

Production evidence must identify which authority and runtime domain it validates.

## Mandatory product invariants

1. PostgreSQL remains authoritative for governed product state.
2. Identity and platform persistence boundaries remain explicit.
3. Object storage does not become lifecycle authority.
4. AI, embeddings and vector databases remain optional.
5. Organization isolation is enforced at backend boundaries.
6. Runtime completion is resolved from persisted evidence where such evidence exists.
7. Published migrations are immutable.
8. Production configuration fails closed.
9. Secrets are not stored in source control or exposed in logs.
10. Determinism, idempotency, lineage and auditability are preserved under retries and failure.

## Production Acceptance domains

### Functional Acceptance

Validate the supported product journeys against the release candidate, including:

- authentication and organization context;
- document registration and version lifecycle;
- storage and verification;
- processing and chunk persistence;
- knowledge publication;
- Enterprise Search;
- assistant/conversation behavior where enabled;
- administration, feedback and audit visibility.

Product Acceptance must never be weakened to hide a runtime defect.

### Security Acceptance

Validate at minimum:

- secure credential and secret handling;
- authentication and session controls;
- CSRF and request-origin protections where applicable;
- authorization and organization isolation;
- secure transport requirements;
- safe production defaults;
- auditable administrative actions;
- absence of development-only credentials or unsafe fallbacks.

### Recovery Acceptance

A backup is not accepted until restore is demonstrated.

Recovery evidence must cover the persistence authorities required by the selected deployment topology, including:

- Platform PostgreSQL;
- Identity PostgreSQL;
- object storage where governed source/derived payloads are required;
- reconciliation of restored lifecycle and runtime evidence.

### Deployment Acceptance

Validate the supported release topology and configuration without changing SHEKU's product semantics.

Deployment topology may differ across local, on-premise, hybrid and cloud environments, but PostgreSQL authority, organization isolation and optional-AI boundaries must remain unchanged.

### Capacity Acceptance

Define and validate a supported operating envelope for the release candidate, including relevant limits for:

- document volume and size;
- processing concurrency;
- database connections;
- storage consumption;
- search latency and bounded queries;
- assistant/provider execution where enabled;
- worker and queue behavior where applicable.

### Observability Acceptance

Operators must be able to distinguish:

- healthy;
- degraded;
- unavailable;
- blocked by configuration;
- blocked by missing persisted evidence;
- optional provider unavailable.

Operational visibility must not infer product readiness solely from process liveness.

### Migration Acceptance

SHEKU has independent platform and identity migration authorities.

For each release candidate, validate:

- expected migration head for each database;
- clean installation path;
- supported upgrade path;
- migration immutability;
- rollback eligibility or explicit non-rollback constraints;
- persisted release/migration evidence where supported.

## AI-independent release requirement

The product core must remain operable with:

```text
LLM = disabled
Embeddings = disabled
Vector database = disabled
```

Production readiness for the core cannot depend on an optional AI provider being available.

If an organization explicitly enables an AI-dependent capability, that capability must expose its own readiness and degraded-state evidence without invalidating unrelated core capabilities.

## Release closure

A release may be classified as production-ready only when its required acceptance domains are complete and no unresolved release blocker remains.

Canonical decision model:

```text
Product Acceptance = PASSED
Security Acceptance = PASSED
Recovery Acceptance = PASSED
Deployment Acceptance = PASSED
Capacity Acceptance = PASSED
Observability Acceptance = PASSED
Platform migration state = VERIFIED
Identity migration state = VERIFIED
release blockers = []
production_ready = true
```


## Related documentation

- `docs/product/sheku-product-definition.md`
- `docs/product/capabilities.md`
- `docs/architecture/overview.md`
