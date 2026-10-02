# Knowledge Engine Architecture

## Purpose

The Knowledge Engine turns processed, governed and published content into retrievable, citeable and access-controlled knowledge.

It is a platform service. It is not tied to a specific industry segment, customer structure, asset class, document taxonomy, storage provider or operational process.

## Current boundary

The Knowledge Engine does not consume uploads directly.

It must not consume:

- `DocumentRecord` alone;
- `DocumentVersion` planning output alone;
- Binary Upload placeholders alone;
- metadata-only artifacts alone;
- unverified storage objects.

It consumes content only after the document lifecycle has reached processing and publication boundaries.

```text
Document Management
-> Processing Session
-> Storage Verification                  [future]
-> Ingestion                             [future]
-> Chunk Persistence                     [future]
-> Knowledge Publication                 [future]
-> Knowledge Engine
-> Retrieval
-> AI                                    [optional]
```

## Product responsibility

The Knowledge Engine is responsible for:

- receiving persisted and approved chunks from ingestion/publication;
- maintaining PostgreSQL full-text retrieval;
- optionally creating embeddings;
- optionally indexing vector representations;
- supporting lexical and optional hybrid retrieval;
- merging retrieval results;
- optionally reranking candidate results;
- selecting diverse context;
- building answer context;
- producing citations;
- enforcing access and classification constraints.

The Knowledge Engine does not own:

- Document Management configuration;
- Document Registration;
- Document Version Planning;
- Binary Upload execution;
- storage provider execution;
- source extraction;
- OCR;
- parsing;
- chunk persistence transactions;
- runtime lease lifecycle;
- mandatory AI generation.

## Mandatory and optional boundaries

Mandatory productive baseline after content has been processed:

```text
PostgreSQL chunks
-> PostgreSQL FTS indexing
-> lexical retrieval
-> context assembly
-> citations
```

Optional derived capabilities:

```text
PostgreSQL chunks
-> embedding generation
-> vector publication
-> semantic retrieval
-> hybrid retrieval
-> model-based reranking
-> optional generated answer
```

Failure or absence of an optional capability must not prevent the mandatory lexical platform from operating.

## Processing handoff

Processing owns source acquisition after storage verification, extraction, OCR when configured, parsing, normalization, chunking, quality filtering and chunk persistence.

The Knowledge Engine consumes committed chunks and published knowledge artifacts only.

```text
document processing succeeds
    after storage verification, extraction, chunk persistence and lexical publication

optional semantic publication
    may execute separately after commit
```

Vector publication must never occur before the corresponding PostgreSQL chunk transaction commits.

## Platform entities

```text
documents.collections
documents.chunks
documents.indexing_jobs
documents.classification_rules
security.roles
security.permissions
security.policies
ai.knowledge_sources
ai.models
ai.agents
runtime.executions
runtime.execution_attempts
runtime.execution_events
audit.audit_events
```

## Retrieval design

Retrieval must be configurable per collection and knowledge source.

Configuration dimensions include:

- PostgreSQL full-text index;
- optional vector collection;
- optional embedding model;
- optional reranker model;
- maximum context size;
- diversity strategy;
- citation requirements;
- security filter mode;
- classification filter mode;
- fallback mode;
- no-AI behavior.

No collection name, vector target, model or provider may be hardcoded as product architecture.

## CPU-first runtime strategy

The Knowledge Runtime must remain useful before any LLM, embedding model or vector provider is configured.

CPU-first capabilities include:

- PostgreSQL Full Text Search retrieval;
- query normalization;
- configurable synonym expansion;
- metadata and classification filtering;
- chunk quality scoring;
- exact and near-duplicate detection;
- deterministic chunk enrichment;
- citation packaging.

## AI boundary

AI is downstream and optional.

```text
Knowledge Engine
-> governed context
-> AI Engine when enabled
-> answer generation
```

The AI Engine may use Knowledge Engine output, but the Knowledge Engine must not require AI to satisfy baseline retrieval and citation behavior.


```text
ai_required = false
embeddings_created = false
vector_store_required = false
```

## Current non-goals

The current document readiness foundation does not implement:

- knowledge publication from uploaded binary;
- retrieval from upload placeholder metadata;
- embedding generation from uploaded binary;
- vector indexing from uploaded binary;
- AI workflow execution from uploaded binary.

These capabilities become valid only after storage execution, ingestion, processing and knowledge publication are implemented.
