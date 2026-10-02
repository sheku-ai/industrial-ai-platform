# SHEKU Code Stability and Change Policy

## Purpose

This policy defines which SHEKU product contracts are controlled and which implementation details may evolve.

SHEKU is not globally immutable. Stability applies to product invariants, domain ownership, published contracts and persisted evidence. Internal implementation may evolve through controlled engineering changes.

## Controlled product invariants

The following may change only through an explicit architecture/product decision:

- PostgreSQL is authoritative for governed product state and lifecycle evidence;
- Identity PostgreSQL remains the authority for identity/authentication/session state;
- object storage owns binary payloads, not lifecycle truth;
- AI is an optional service layer;
- SHEKU must operate without mandatory LLMs, embeddings or vector databases;
- organization isolation is mandatory at backend boundaries;
- Community and Enterprise remain architecturally separable;
- customer-specific concepts must not become fixed SHEKU entities;
- routine administration is configuration-driven;
- vector indexes and other derived indexes remain rebuildable and non-authoritative;
- Product Acceptance must not be weakened to hide runtime defects.

## Domain ownership

Moving authority between domains requires explicit architecture validation and a migration/compatibility plan.

Representative ownership boundaries:

```text
Platform PostgreSQL
= product configuration
+ organizations and domain ownership
+ lifecycle state
+ governed knowledge
+ runtime evidence

Identity PostgreSQL
= identities
+ authentication
+ governed sessions
+ identity audit

Object storage
= source and derived binary payloads

Operational control plane
= coordination and scheduling, not lifecycle authority
```

A refactor inside a domain may change implementation without changing ownership semantics.

## Published contracts

Published contracts include:

- API routes and payload schemas;
- persistent data constraints used as product contracts;
- lifecycle/event semantics;
- runtime evidence contracts;
- artifact contracts;
- configuration schemas;
- adapter/extension interfaces;
- edition boundaries;
- supported migration and upgrade semantics.

Contract changes must be classified as:

- backward compatible;
- backward compatible with deprecation;
- breaking and versioned;
- internal-only.

Breaking changes require explicit approval, migration/compatibility design and validation evidence.

## Internal implementation

Internal implementation remains changeable when product contracts and invariants are preserved. Examples include:

- service internals;
- repository implementation;
- worker implementation;
- algorithms;
- module layout;
- query optimization;
- caching;
- retry/backoff implementation;
- UI composition;
- test infrastructure;
- deployment packaging.

Existing code is not protected merely because it already exists. It may be replaced when the change improves correctness, maintainability, security, scalability or product clarity without violating controlled boundaries.

## Configuration versus code

Routine product administration must be represented through supported configuration, API and UI contracts rather than source-code edits.

Examples include:

- enabled/disabled state;
- organization scope;
- provider selection;
- governed operation parameters;
- scheduling policy where supported;
- retention configuration where supported;
- connector configuration;
- model/prompt/guardrail configuration where AI is enabled.

This does not make source code immutable.

SHEKU must not accept arbitrary scripts, unrestricted shell commands or unrestricted SQL as normal runtime configuration.

## Change classes

### Class A — Internal refactor

No intended external contract change.

Examples:

- reorganizing modules;
- optimizing queries;
- extracting reusable services;
- replacing an internal implementation.

Expected evidence: static/regression validation appropriate to the affected domain and confirmation that published contracts are unchanged.

### Class B — Compatible product change

Adds or extends behavior without breaking existing supported contracts.

Examples:

- an optional API field;
- a new adapter implementation;
- a new registered operation;
- an additional readiness indicator.

Expected evidence: compatibility, authorization/organization isolation, persistence and release documentation when applicable.

### Class C — Contract migration

Changes a published contract or ownership/lifecycle semantic.

Examples:

- API response restructuring;
- lifecycle state semantic change;
- moving persistent ownership;
- changing canonical identifiers;
- changing migration expectations.

Required: architecture validation, version/deprecation strategy, migration design when persistence changes, rollback/compatibility analysis and explicit validation evidence.

### Class D — Architectural invariant change

Changes a foundational SHEKU rule.

Examples:

- replacing PostgreSQL as product authority;
- making AI mandatory;
- allowing a vector index or object store to determine governed completion;
- removing organization isolation;
- merging Community and Enterprise into inseparable runtime dependencies;
- introducing fixed customer-specific architecture.

These changes are presumed rejected unless an explicit product-level decision approves them with impact analysis, migration strategy and release-level governance.

## Stable component criteria

A component is considered stable when its responsibilities and ownership are explicit, public contracts are understood, migration behavior is defined where relevant, authorization and organization isolation are known, failure modes are observable, and compatible evolution can be performed without hidden state authority.

Passing a test suite alone does not define architectural stability.

## Immutability

Immutability applies only where SHEKU explicitly requires append-only or historical behavior, for example:

- published migration history;
- audit history;
- runtime execution evidence where modeled as historical records;
- canonical historical revisions;
- persisted release evidence that must remain attributable.

Application source code, schemas and APIs evolve through controlled change rather than global immutability.

## Release rule

Before a SHEKU release is declared production-ready, release governance must define or validate the applicable compatibility, migration, upgrade, rollback, security and extension-support expectations.

Production-readiness requirements are maintained in `docs/deployment/PRODUCTION_READINESS.md`.

## Decision

```text
SHEKU implementation = CONTROLLED EVOLUTION
architectural invariants = CONTROLLED
published contracts = VERSIONED / GOVERNED
routine administration = CONFIGURATION DRIVEN
arbitrary runtime code configuration = PROHIBITED
```
