# Ingestion Engine Architecture

## Purpose

The Ingestion Engine converts verified stored content into governed, persistent and retrievable platform knowledge assets.

It is a generic platform capability. It must not assume a specific company, industry, asset class, department, location hierarchy, document taxonomy, country, metadata model, storage provider or business process.

## Current boundary

The Ingestion Engine is not triggered directly by Document Registration, Document Version Planning or Binary Upload Execution.


```text
Document Registration
-> Document Version Planning
-> Binary Upload Planning
-> Binary Upload Execution Foundation
-> Artifact Placeholder
-> Upload Session
-> Processing Session
-> Storage Execution                         [future]
-> Ingestion                                 [future]
```

Ingestion may start only after a future storage execution step verifies that the binary exists and is readable through a configured storage provider.

## Product responsibility

The engine is responsible for future execution of:

- registering ingestion intent;
- associating ingestion work with a durable runtime execution;
- acquiring and validating verified source content;
- resolving an enabled adapter through configuration and capabilities;
- extracting and normalizing content;
- coordinating optional OCR when configured;
- parsing structured or unstructured content;
- generating controlled chunks;
- applying quality policies;
- persisting chunks in PostgreSQL;
- publishing derived artifacts;
- creating or executing lexical indexing work;
- scheduling optional semantic publication;
- exposing auditable outcomes.

The engine is not responsible for Document Registration, Document Version Planning, Binary Upload placeholder creation, physical object upload execution, storage provider configuration, generated answers, mandatory embeddings, mandatory vector storage or customer-specific routing.

## Target productive flow

```text
processing session approved
-> storage verified
-> ingestion request
-> documents.ingestion_job
-> runtime execution
-> runtime lease and attempt
-> source acquisition
-> source validation
-> configurable adapter resolution
-> optional OCR
-> parsing and extraction
-> normalization
-> chunking
-> quality filtering
-> PostgreSQL chunk persistence
-> artifact publication
-> PostgreSQL lexical indexing
-> ingestion success
-> optional embedding execution
-> optional vector publication
```

PostgreSQL persistence and lexical indexing form the mandatory productive baseline. Embedding generation and vector publication are derived, optional capabilities.

## Relationship to Document Processing Session

The Processing Session is the readiness bridge before ingestion.

It prepares stages:

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

Only after the storage verification stage succeeds may ingestion move from readiness to execution.

## Platform entities

```text
documents.document_records
documents.document_versions
documents.artifacts
documents.ingestion_jobs
documents.chunks
documents.indexing_jobs
documents.document_types
documents.metadata_templates
documents.classification_rules
documents.retention_policies
documents.collections
runtime.executions
runtime.execution_attempts
runtime.execution_events
runtime.execution_artifacts
connectors.connectors
connectors.connector_runs
audit.audit_events
```

`documents.artifacts` may represent a metadata-only binary upload placeholder before real storage execution. It is not proof that a binary exists in object storage.

## Runtime and domain ownership

```text
runtime
    technical execution, attempts, leases, retries, cancellation and events

documents
    document records, document versions, artifacts, ingestion configuration, processing revisions and chunks

storage provider
    future physical object execution and verification

object storage
    source objects and derived artifacts after real storage execution

knowledge services
    lexical and optional semantic publication
```

The ingestion runtime uses:

```text
execution_type = document.ingestion
subject_type = document_version
subject_id = document_version_id
```

Runtime status and domain status remain separately owned. No cross-schema synchronization trigger is used.

## Runtime components

```text
Ingestion API
RuntimeWorkerService
DocumentIngestionRuntimeAdapter
IngestionPipelineCoordinator
SourceAcquisitionService
IngestionAdapterResolver
IngestionAdapter
OptionalOCRService
ParsingService
NormalizationService
ChunkingService
QualityService
DocumentPersistenceService
KnowledgePublicationBridge
```

These components must be reached only through explicit lifecycle transitions. Binary Upload Execution must not call them directly.

## Mandatory and optional capabilities

Mandatory ingestion baseline after execution starts:

```text
source validation
-> extraction / parsing
-> normalized text or structured representation
-> chunking
-> PostgreSQL chunk persistence
-> PostgreSQL lexical indexing
```

Optional capabilities:

```text
OCR
visual enrichment
semantic embeddings
vector publication
AI-assisted enrichment
```

Optional capability failure must not break the mandatory no-AI baseline unless the configured processing profile explicitly requires that capability.

## Safety rules

- Ingestion must not start from `DocumentRecord` alone.
- Ingestion must not start from a metadata-only upload placeholder alone.
- Ingestion requires verified storage state.
- OCR, parsing, chunking, enrichment, embeddings and knowledge publication must remain separately controllable stages.
- AI must remain optional.
- PostgreSQL remains the source of truth for lifecycle state.

## Current non-goals

The current document readiness foundation does not implement real storage verification, ingestion job creation from upload placeholder, OCR execution from uploaded binary, parsing execution from uploaded binary, chunk generation from uploaded binary, embedding generation from uploaded binary or knowledge publication from uploaded binary.

These become valid only after storage execution and verification are implemented.
