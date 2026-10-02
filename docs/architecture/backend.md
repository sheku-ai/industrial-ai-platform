# Backend Architecture

## Current Position

The backend follows a layered architecture:

```text
Admin Portal / API
→ Workspace Runtime
→ Domain Runtime
→ Repository
→ PostgreSQL
```

PostgreSQL is the source of truth. Workspace runtimes are read-only aggregation layers that compose existing domain runtimes into normalized product-facing contracts.

## Layer Responsibilities

### API Layer
Responsible for routing, request validation, authentication, dependency injection and response serialization. Business orchestration must not live in routes.

### Workspace Runtime Layer
Provides read-only product views for the Admin Portal. Aggregates existing domain runtimes and repositories into normalized responses. Never creates persistence, executes AI, triggers workers or calls external systems.

### Domain Runtime Layer
Owns business behavior and lifecycle execution. It is the single implementation point for domain logic.

### Repository Layer
Encapsulates persistence concerns and exposes PostgreSQL-backed entities. No orchestration logic.

## Architectural Principles

- PostgreSQL is the only source of truth for platform state.
- Workspace runtimes compose existing capabilities; they do not replace them.
- Domain runtimes own lifecycle execution.
- AI, embeddings and vector indexes are optional service layers.
- Every workspace endpoint is read-only and free of side effects.
- External providers must never be invoked by workspace runtimes.
- New capabilities should extend existing runtimes before introducing new abstractions.

## Product Runtime Graph

```text
Configuration
→ Registration
→ Storage
→ Processing
→ Chunk Generation
→ Knowledge Publication
→ Knowledge Index
→ Enterprise Search
→ Assistant
→ Feedback
→ Audit
→ Operations
→ Governance
```
## Scalability and Performance Position

Workspace runtimes are stateless read-only aggregation layers. They should be safe to scale horizontally behind the API layer.

Large workspace responses must evolve toward pagination, SQL aggregation, explicit response size limits, indexed lifecycle queries, bounded recent-activity windows and predictable timeout behavior.

Current pre-production workspace runtimes prioritize product completeness and visibility. Production hardening must review every workspace runtime for N+1 query risks, expensive joins, unbounded reads and slow response paths.

## Production Hardening Requirements

Before release candidate, the backend must complete a dedicated hardening pass covering structured logging, runtime metrics, trace identifiers, health endpoints, database indexes, query plans, error handling, retry boundaries and deployment configuration validation.

This phase must not add product features. Its purpose is operational reliability, performance and release readiness.

## Extensibility Rules

New backend capabilities must follow the existing runtime graph.

A new domain should add or extend a domain runtime. A new product experience should add or extend a workspace runtime that composes existing domain runtimes.

Do not introduce customer-specific terminology, hardcoded organizational structures, fixed roles, fixed document taxonomies or fixed operational models.

AI must remain optional. The platform must remain useful without LLMs, embeddings or vector search.

Community and Enterprise separation must remain possible from the architecture.

## Next Architectural Priorities

Governance Center
Product Integration Review
Security Center
Search and Discovery Center
Workflow Studio
Reporting and Analytics Center
Production Readiness
Production Hardening
Code Quality Normalization
Release Candidate