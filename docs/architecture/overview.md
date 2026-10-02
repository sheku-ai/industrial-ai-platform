# SHEKU Architecture Overview

**SHEKU — Knowledge into action.**

## Purpose

This document is the canonical architecture overview for the SHEKU 1.6.x release line.

SHEKU is a generic, configurable and deployment-neutral governed enterprise knowledge platform for industrial organizations. It is not a customer-specific implementation and it is not a RAG-only product.

PostgreSQL is authoritative for governed product state. AI remains an optional service layer.

## Architecture invariants

1. PostgreSQL is authoritative for product configuration, lifecycle state, governed knowledge and runtime evidence.
2. Identity PostgreSQL is authoritative for authentication, identities and governed sessions.
3. Object storage stores source and derived binary payloads, not lifecycle truth.
4. PostgreSQL Full Text Search is the governed lexical baseline for Enterprise Search.
5. Embeddings, vector stores, semantic retrieval and AI reranking are optional derived capabilities.
6. AI providers are optional consumers of governed knowledge.
7. Organization isolation is enforced at backend persistence and runtime boundaries.
8. Persisted evidence takes precedence over transient flags, caches or in-memory state.
9. Determinism, idempotency, lineage and auditability are product requirements.
10. Provider choice must not define the product domain model.

## Runtime graph

```text
Configuration
-> Registration
-> Storage
-> Processing
-> Knowledge
-> Search
-> Assistant
-> Conversation
-> Feedback
-> Audit
```

Each runtime consumes persisted evidence from upstream stages or produces persisted evidence for downstream stages.

## Document and knowledge lifecycle

```text
Document Registration
-> Document Version
-> Binary Upload
-> Storage Execution
-> Storage Verification
-> Artifact + DocumentVersion persistence
-> Processing
-> Chunking
-> Knowledge Publication
-> PostgreSQL Knowledge Index
-> Enterprise Search
```

Documents are governed entities with versioning, organization scope, metadata, lifecycle state and lineage.

Processing is a persisted runtime, not an implicit side effect of upload. Knowledge publication occurs only after the required upstream evidence exists.

## Knowledge ownership

The durable asset in SHEKU is governed knowledge, not a particular vector index or model provider.

```text
Knowledge Entry
-> Knowledge Publication
-> Processing Evidence
-> Document Version
-> Source Artifact
```

A search result, citation or assistant answer must be traceable to governed source evidence whenever the participating runtime supports provenance.

## Enterprise Search

Enterprise Search is independent from AI execution.

```text
Governed Knowledge
-> PostgreSQL FTS
-> Authorized Enterprise Search
```

Optional semantic retrieval may extend lexical retrieval through embeddings, vector storage, hybrid candidate merging or reranking. These derived capabilities are rebuildable and are never the source of truth for knowledge.

## Assistant and conversation runtime

```text
Assistant Definition
-> Assistant Session
-> Conversation
-> Conversation Turn
-> Assistant Runtime
-> Retrieval
-> Enterprise Search
-> Context Builder
-> Prompt Assembly
-> optional LLM Gateway
-> optional Provider Execution
-> Citation Verification
-> Assistant Response Runtime
-> Conversation Runtime
```

Assistant and conversation state is persisted to support organization isolation, idempotency, retries, correlation, history and auditability.

Provider execution may be disabled or unavailable while document management, governed knowledge and Enterprise Search remain functional.

## Security and organization isolation

```text
Identity PostgreSQL
-> identities
-> authentication credentials
-> governed sessions
-> identity audit

Platform PostgreSQL
-> organizations
-> memberships and authorization references
-> roles and permissions
-> documents and artifacts
-> governed knowledge
-> search runtime
-> assistant and conversation runtime
-> operational evidence
```

A portal-selected organization is request context, not an authorization boundary.

Authorization governs both access to source documents and whether derived knowledge may participate in Enterprise Search or assistant context.

## Persistence ownership

```text
Platform PostgreSQL = authoritative product and knowledge state
Identity PostgreSQL = authoritative identity and session state
Object storage = source and derived binary payloads
PostgreSQL FTS = governed lexical search baseline
Vector storage = optional derived semantic index
Embeddings = optional derived data
AI = optional service layer
```

Caches and in-memory state may improve performance but cannot determine authoritative completion or ownership.

## Evidence-first runtime progression

The expected pattern is:

```text
persist authoritative evidence
-> evaluate gate from persisted evidence
-> expose readiness/capability state
-> continue runtime
```

not:

```text
set convenience flag
-> assume completion
```

## Provider-neutral extension boundaries

External implementations are adapters around stable SHEKU contracts. Relevant extension domains include:

```text
Storage adapters
Processing adapters
Connector adapters
Search strategies
Embedding providers
Vector providers
LLM providers
```

Registries should exist when multiple real implementations justify them. Speculative abstractions should not be introduced without a product need.

## Deployment neutrality

The product model supports local, on-premise, hybrid and cloud deployments without changing knowledge ownership or lifecycle semantics.

Deployment topology may vary, but the following invariants do not:

- PostgreSQL remains authoritative;
- object storage remains non-authoritative for lifecycle state;
- organization isolation remains mandatory;
- optional AI remains separable from the knowledge core;
- release and operational evidence remain persisted.

## No-AI baseline

SHEKU must remain operational for its core responsibilities with:

```text
LLM = disabled
Embeddings = disabled
Vector database = disabled
```

The mandatory baseline includes identity and authorization, organization isolation, document lifecycle, storage and verification, processing and chunk persistence, governed knowledge publication, PostgreSQL knowledge indexing, Enterprise Search, runtime evidence and auditability.

## Architecture evolution

Architecture changes must extend these boundaries rather than create parallel runtimes or provider-specific product models.

