# Serving Engine Architecture

## Purpose

The Serving Engine exposes platform capabilities through stable APIs and application-facing services.

It must expose product-level contracts. It must not expose implementation-specific worker names, collection names, customer terminology, storage-provider internals or historical project concepts.

## Product responsibility

The Serving Engine is responsible for:

- API route composition;
- request validation;
- authentication and authorization integration;
- platform configuration APIs;
- document management APIs;
- binary upload readiness APIs;
- processing readiness APIs;
- retrieval APIs;
- assistant APIs when AI is enabled;
- ingestion registration APIs when processing execution is enabled;
- feedback APIs;
- audit event creation;
- health and readiness endpoints.

## Current baseline

The serving baseline includes:

```text
FastAPI application
PostgreSQL-backed configuration APIs
Core API group
Documents API group
Security API group
Connectors API group
AI API group
Runtime and operations API groups
Document readiness API contracts
Admin Portal persistence path
```

## Target service groups

```text
/api/core
/api/documents
/api/documents/versions
/api/documents/versions/uploads
/api/documents/processing
/api/security
/api/connectors
/api/ai
/api/ingestion
/api/knowledge
/api/audit
/api/runtime
```

## Document readiness serving path

```text
Client request
-> Serving Engine API
-> request schema validation
-> service-layer lifecycle validation
-> PostgreSQL-backed state read/write
-> response serializer
-> audit-ready result
```

Current document readiness endpoints include:

```text
POST /api/documents/registration/prevalidate
POST /api/documents/registration/plan
POST /api/documents/registration/execute
POST /api/documents/versions/plan
POST /api/documents/versions/uploads/plan
POST /api/documents/versions/uploads/execute
GET  /api/documents/versions/uploads/{artifact_id}/status
GET  /api/documents/processing/{artifact_id}/status
```

The Serving Engine must preserve the separation between:

- document metadata lifecycle;
- binary upload readiness;
- storage provider execution;
- ingestion execution;
- knowledge publication;
- AI orchestration.

## Retrieval serving path

```text
User request
-> Serving Engine API
-> Security context resolution
-> Agent or retrieval configuration lookup
-> Knowledge Engine query
-> AI Engine orchestration when enabled
-> Citation packaging
-> Audit event creation
-> Response
```

## Non-AI mode

The Serving Engine must support non-AI operation.

In non-AI mode, the platform must still provide:

- configuration management;
- document management;
- binary upload readiness;
- processing readiness;
- connector configuration;
- enterprise search using non-AI retrieval where available;
- audit history;
- governance controls.

## Storage execution boundary

The Serving Engine may expose future storage execution endpoints only through a dedicated storage execution gateway.

Document Management routes must not directly call MinIO, S3, Azure Blob, filesystem or any concrete storage provider.

## API design rule

Serving contracts should be stable, additive where possible and provider-neutral. Internal DTOs, workers, adapters and storage provider implementations must remain hidden behind service-layer contracts.
