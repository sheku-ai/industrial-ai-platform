# Workspace Runtime Architecture

## Purpose

Workspace Runtimes define the product-facing aggregation layer of the Industrial AI Platform.

They exist to transform multiple domain runtimes, repositories and runtime services into a single normalized contract consumed by the Admin Portal.

Workspace Runtimes are not business services.

They are not orchestration engines.

They are not workflow engines.

They are read-only product composition layers.

---

## Architectural Position

```text
Admin Portal
→ Workspace Component
→ Runtime API Client
→ Workspace Runtime
→ Domain Runtime
→ Repository
→ PostgreSQL
```

Every Workspace Runtime sits between the UI and the domain layer.

The UI never aggregates multiple business domains directly.

The Workspace Runtime performs that composition.

---

## Objectives

Workspace Runtimes exist to:

- expose a complete product experience;
- aggregate multiple domains into one response;
- normalize contracts across workspaces;
- expose readiness, diagnostics and evidence;
- reduce frontend complexity;
- keep business logic inside domain runtimes.

---

## Responsibilities

A Workspace Runtime may:

- aggregate repositories;
- aggregate domain runtimes;
- aggregate runtime services;
- calculate summary metrics;
- expose readiness indicators;
- expose diagnostics;
- expose warnings;
- expose pending capabilities;
- expose recent activity;
- expose operational evidence.

A Workspace Runtime must not:

- create persistence;
- modify configuration;
- execute AI;
- execute connectors;
- enqueue jobs;
- trigger workers;
- retry processing;
- mutate lifecycle state;
- call external systems;
- expose secrets.

---

## Source of Truth

Workspace Runtimes always consume governed platform state.

```text
PostgreSQL
=
Source of Truth
```

Optional technologies such as embeddings, vector indexes and LLMs are derived capabilities and must never become authoritative.

---

## Runtime Contract

Every Workspace Runtime should expose a normalized contract containing:

- workspace summary;
- readiness status;
- operational metrics;
- diagnostics;
- warnings;
- blocking issues;
- pending capabilities;
- domain-specific sections;
- evidence;
- timestamps where appropriate.

A consistent contract allows the Admin Portal to evolve independently of individual domain implementations.

---

## Implemented Workspace Runtimes

Current platform workspaces include:

```text
Platform Home
Platform Dashboard Runtime
Platform Administration Runtime
Platform Operations Runtime
Operations Center Runtime
Document Workspace Runtime
Knowledge Workspace Runtime
Assistant Workspace Runtime
AI Studio Runtime
Connector Workspace Runtime
Governance Center Runtime
```

Future workspaces should follow the same composition model.

---

## Design Principles

1. Product-first.
2. Read-only.
3. Runtime composition over duplication.
4. PostgreSQL as the authoritative state.
5. Optional AI.
6. Explicit diagnostics.
7. Stable contracts.
8. Customer-neutral terminology.
9. Extensible by composition.
10. Safe for production.

---

## Production Expectations

Before Release Candidate every Workspace Runtime should be reviewed for:

- SQL efficiency;
- pagination;
- response size;
- timeout behaviour;
- N+1 queries;
- caching opportunities;
- observability;
- structured logging;
- metrics;
- traceability.

Workspace Runtimes are expected to become one of the core architectural patterns of the platform and should remain stable across future releases.
