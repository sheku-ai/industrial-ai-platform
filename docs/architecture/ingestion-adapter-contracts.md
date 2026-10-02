# Ingestion Adapter Contracts

## Status

```text
Sprint: 25.1
Architecture status: VALIDATED FOR IMPLEMENTATION
Provider execution: DISABLED
AI requirement: NONE
```

## Decision

Historical ingestion scripts are reusable implementation assets only. They do not define platform terminology, metadata, persistence, routing or deployment architecture.

The platform adapter boundary is defined by:

```text
apps/api/app/services/ingestion_adapter_contracts.py
```

An ingestion adapter receives a generic `AdapterInput` and returns an `AdapterExecutionResult`. It must not directly own the platform database lifecycle, knowledge indexing policy, organization model, security model or object-storage metadata model.

## Generic execution boundary

### Input

Every adapter receives:

- organization identifier;
- document identifier;
- document-version identifier;
- source reference;
- original file name;
- declared media type;
- checksum;
- content length;
- configurable metadata;
- configurable execution options;
- idempotency key;
- attempt number.

No fixed company, location, department, asset, classification or document-family field is part of the adapter contract.

### Output

Every adapter returns:

- execution status;
- zero or more normalized chunks;
- zero or more derived artifacts;
- metrics;
- controlled error code and message;
- optional retry delay.

Adapters do not return embeddings, vector-store records or database-specific models.

## Inventory of reusable assets

| Platform adapter key | Historical implementation asset | Intended responsibility | Direct coupling found | Required normalization |
|---|---|---|---|---|
| `text` | `worker_ingest_text.py` | Decode and normalize text-like sources; produce deterministic chunks and extraction artifacts | Local filesystem; environment variables; shared legacy helper names | Wrap behind `AdapterInput`; remove legacy module names; emit `AdapterExecutionResult`; move artifact publication outside extractor |
| `rich-document` | `worker_ingest_pdf.py` | Extract rich-document content with optional OCR and page-aware provenance | Local filesystem; external binaries; MarkItDown; OCR tools; environment variables | Split extraction from OCR provider selection; preserve optional OCR; normalize page provenance; prohibit direct publication or persistence |
| `spreadsheet` | `worker_ingest_excel.py` | Extract tabular structures, row chunks and summaries | Local filesystem; pandas; environment variables; hardcoded sheet profiles and domain-oriented heuristics | Replace fixed sheet profiles with configurable parsing profile; remove domain keyword assumptions; preserve row/cell provenance |
| `ndjson` | `worker_load_chunks_ndjson.py` | Validate and load controlled chunk artifacts | PostgreSQL; Qdrant; embedding model; filesystem; fixed infrastructure defaults | Split artifact validation, PostgreSQL chunk persistence, optional embedding generation and optional vector publication into separate services |
| `dispatcher` | `worker_daemon.py` | Claim work, retrieve source payload, route execution and publish lifecycle results | PostgreSQL; MinIO; subprocesses; filesystem; legacy registry schema; fixed metadata fields | Replace with platform runtime execution claims, configurable adapter registry and supported object-storage service; remove legacy registry model |
| `shared helpers` | `iaom_worker_common.py` | Hashing, normalization, chunk construction and artifact writing | Filesystem; environment variables; legacy naming | Extract pure utility functions; inject runtime configuration; remove generated absolute paths and legacy module identity |
| `quality helpers` | `iaom_worker_quality.py` | Quality classification and chunk filtering | Historical taxonomy assumptions | Convert into configurable quality-policy service with generic defaults |

## Coupling decisions

### Database

Adapters must not open PostgreSQL connections. PostgreSQL persistence belongs to the platform persistence service after adapter output validation.

### Object storage

Adapters may read through an injected source-access abstraction. They must not create provider-specific clients or define bucket/key policy.

### Embeddings and vector stores

Embeddings and vector publication are downstream optional services. They are never adapter requirements.

### Filesystem

A worker runtime may materialize a source into an isolated execution workspace. The workspace path is supplied by the runtime and is not generated from fixed deployment directories inside the adapter.

### External binaries

OCR and document-conversion binaries are optional capabilities declared by the adapter descriptor. Their absence must produce a controlled capability or retryable error, not redefine platform readiness.

## Routing

Routing uses configured descriptors and matches file extension and/or declared media type.

Rules:

1. no match produces a controlled routing error;
2. multiple adapter matches are rejected as ambiguous;
3. adapters are disabled by default until registered and configured;
4. extension lists and media-type lists are platform configuration inputs;
5. routing cannot depend on organization-specific metadata.

The built-in inventory is a migration baseline, not a hardcoded activation policy.

## Idempotency and retry

- The platform creates the idempotency key.
- The adapter receives the current attempt number.
- A successful adapter execution must be safe to persist once.
- Retryable results require a stable error code and may include a retry delay.
- Persistence and artifact publication must independently enforce idempotency.

## Required implementation order

1. implement a registered platform-worker adapter interface;
2. migrate the text implementation first;
3. separate workspace/source access from extraction;
4. validate normalized chunks and artifacts;
5. persist through supported APIs or repositories;
6. add retry and idempotency evidence;
7. repeat for rich documents, spreadsheets and NDJSON loading.

## Explicitly rejected architecture

The following historical behavior must not be promoted into the product:

- direct use of a legacy document registry as the platform source of truth;
- fixed organization or operational metadata fields in worker contracts;
- direct Qdrant writes from the NDJSON parser;
- mandatory embedding model loading during chunk persistence;
- infrastructure IP addresses or credentials embedded in code;
- hardcoded spreadsheet sheet names or business-oriented header keywords;
- routing implemented only by a monolithic subprocess daemon;
- object-storage publication owned by extraction code.
