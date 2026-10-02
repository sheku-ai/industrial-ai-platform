# SHEKU Controlled Ingestion E2E

## Purpose

This E2E validates a bounded PostgreSQL-backed ingestion and lexical knowledge path without requiring AI, embeddings or vector retrieval.

It uses controlled persistence and intentionally does not represent the complete binary upload/object-storage document lifecycle. It therefore complements, rather than replaces, Product Acceptance for the full governed document chain.

## Command

From the repository root:

```powershell
python scripts/e2e_optional_ingestion.py
```

The script name is a retained technical identifier.

## Flow

The script:

1. starts the local Compose runtime used by the harness;
2. creates a generic temporary organization;
3. registers a document and ingestion job;
4. claims the job through the ingestion API;
5. transitions the job through its governed execution states;
6. persists one controlled chunk in PostgreSQL;
7. creates and runs a `postgres_fts` indexing job;
8. validates lexical retrieval through the knowledge API;
9. verifies governed records directly in PostgreSQL;
10. removes temporary records;
11. shuts down the harness runtime;
12. writes machine-readable evidence.

## No-AI contract

The harness validates:

```text
embeddings = disabled
vector retrieval = disabled
LLM execution = disabled
retrieval mode = lexical
```

PostgreSQL persists the governed knowledge/indexing evidence used by this harness.

## Evidence

Evidence is written to:

```text
runtime/evidence/optional-ingestion-e2e.json
```

A successful execution must prove the controlled document/job/chunk/index path and retrieval of the controlled chunk.

## Scope boundary

This harness does not claim readiness for:

- binary upload and storage verification;
- external source adapters;
- OCR or provider-specific extraction;
- object-storage recovery;
- semantic/vector retrieval;
- AI-assisted answer execution.

Those capabilities require their own persisted evidence and acceptance paths.

The canonical full lifecycle is documented in `docs/architecture/overview.md`.
