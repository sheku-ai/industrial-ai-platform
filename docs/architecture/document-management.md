# Document Management Architecture

## Purpose

This document defines the current product architecture for the Industrial AI Platform document lifecycle foundation.

Document Management is a generic platform capability. It must support configurable document lifecycle behavior for any industrial organization without encoding customer-specific organizations, sites, assets, departments, document families or metadata.

The domain is intentionally separated from storage, ingestion, OCR, chunking, embeddings, knowledge indexing and AI.

## Current scope

```text
Document Management Configuration
-> Document Registration
-> Document Version Planning
-> Binary Upload Planning
-> Binary Upload Execution Foundation
-> Upload Session Control Plane
-> Document Processing Readiness
```

## Configuration foundation

The platform supports configuration for:

- document types;
- metadata templates;
- retention policies;
- classification rules;
- collections;
- document type profiles;
- validation contracts;
- catalog and summary views.

All configuration must be exposed through UI/API-compatible contracts. No document type, metadata field, organization, role or collection may be hardcoded for a specific customer or industry scenario.

## Document Registration

Document Registration is the first lifecycle step.

It supports:

- prevalidation;
- planning;
- execution;
- idempotency by external reference;
- creation of `DocumentRecord` only.

It must not:

- create `DocumentVersion`;
- upload files;
- create artifacts;
- call storage;
- execute ingestion;
- perform OCR;
- parse documents;
- create chunks;
- create embeddings;
- index vectors;
- activate AI.

## Document Version Planning

Document Version Planning is non-destructive.

It resolves:

- existing `DocumentRecord`;
- candidate next version number;
- version candidate metadata;
- pending prerequisites;
- next available actions.

It does not create a `DocumentVersion` yet.

## Binary Upload Planning

Binary Upload Planning is non-destructive.

It resolves:

- whether a `DocumentRecord` exists;
- whether a `DocumentVersion` exists or is a pending prerequisite;
- upload allowed / blocked state;
- expected file name;
- allowed MIME types;
- maximum size;
- pending prerequisites;
- next available actions.

It does not write binary content or create storage objects.

## Binary Upload Execution Foundation

Binary Upload Execution creates a metadata-only placeholder using existing `documents.artifacts`.

It records:

- file name;
- content type / MIME type;
- size bytes;
- upload pending status;
- source metadata;
- requested by;
- idempotency state;
- execution flags;
- storage provider descriptor;
- storage operation plan;
- runtime trace.

It explicitly does not:

- upload binary content;
- call MinIO, S3, Azure Blob or filesystem;
- compute checksum from real content;
- create ingestion jobs;
- run OCR;
- parse documents;
- create chunks;
- create embeddings;
- publish to knowledge;
- activate AI or workflows.

## Upload Session

Upload Session is an internal domain representation. It is not a database table.

It represents:

- upload session ID;
- artifact ID;
- document record ID;
- document version ID;
- requested operation;
- execution mode;
- runtime state;
- storage provider descriptor;
- storage operation plan;
- execution flags;
- next available actions.

The Upload Session serializer is the canonical response source for execute, replay and status views.

## Upload Control Plane

The Upload Control Plane provides read-only operational state.

It exposes:

- upload session status;
- validation results;
- blocking issues;
- warnings;
- control capabilities;
- future session actions.

Current future actions remain non-executable:

```text
prepare_upload
replace_placeholder
configure_storage
execute_storage
start_ingestion
```

## Document Processing Readiness

Document Processing Readiness starts after an upload placeholder exists.

It is represented by an internal Processing Session and a read-only Processing Control Plane.

It prepares, but does not execute, stages:

```text
binary_available
storage_verified
extraction_ready
ocr_ready
parser_ready
chunking_ready
enrichment_ready
embedding_ready
publication_ready
```

Future actions remain blocked until storage execution and verification exist:

```text
verify_storage
extract_document
execute_ocr
parse_document
generate_chunks
enrich_document
generate_embeddings
publish_to_knowledge
```

## Public API surface

Current document lifecycle readiness endpoints include:

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

## Architectural rule

Document Management owns metadata and lifecycle readiness. It does not own physical storage execution, ingestion execution, knowledge publication or AI execution.

Those capabilities must remain separate platform services connected by explicit lifecycle transitions.
