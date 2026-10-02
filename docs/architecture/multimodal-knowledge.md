# Multimodal Knowledge Architecture

## Purpose

This document defines the product architecture for governed multimodal knowledge in the Industrial AI Platform.

The architecture is generic. It does not assume a company, industry, asset class, location model, department, document taxonomy, country or business process.

## Core principle

```text
source text = authoritative evidence
visual description = derived evidence
```

Visual understanding may enrich retrieval, but it must never replace, overwrite or silently reinterpret authoritative extracted text.

## Mandatory and optional boundaries

Mandatory baseline:

```text
source acquisition
-> configured extraction adapter
-> text normalization
-> PostgreSQL chunk persistence
-> PostgreSQL FTS
-> context assembly
-> citations
```

Optional multimodal path:

```text
embedded image extraction
-> optional visual understanding provider
-> visual-enrichment/v1 artifact
-> visual knowledge records
-> visual chunks
-> lexical and optional semantic retrieval
-> multimodal context and citations
```

Failure or absence of the optional path must not invalidate textual ingestion.

## Runtime composition

```text
DocumentIngestionRuntimeAdapter
-> VisualEnrichmentRuntimeAdapter
-> KnowledgeArtifactRuntimeAdapter
    -> RuntimeVisualChunkIndexingService
        -> VisualKnowledgeChunkMaterializer
```

Rules:

- dependencies are injected explicitly;
- adapters do not inspect private delegate state;
- visual indexing remains optional;
- each service owns one platform responsibility;
- PostgreSQL transactions remain owned by application services;
- providers do not define business entities or product terminology.

## Evidence model

Authoritative text chunk metadata defaults:

```text
content_modality = text
evidence_role = authoritative
authoritative = true
derived_content = false
citation_basis = source_text
```

Derived visual chunk metadata:

```text
content_modality = visual_description
evidence_role = derived
authoritative = false
derived_content = true
citation_basis = derived_visual_description
image_id
image_hash
source_kind
source_locator
provider_key
provider_version
processing_profile
configuration_fingerprint
visual_status
```

## Identity and idempotency

Visual identity is stable by image hash and chunk key.

Database uniqueness rules:

```text
revision-scoped visual chunk:
  organization_id + processing_revision_id + chunk_key

legacy or unscoped visual chunk:
  organization_id + document_version_id + chunk_key
```

`chunk_index` preserves order but is not the logical identity.

Concurrent materialization uses PostgreSQL transaction advisory locking to protect index allocation and atomic `ON CONFLICT DO NOTHING` insertion to prevent duplicates.

## Processing revisions

Reprocessing creates a new processing revision. Previous revision output is retained and is not silently overwritten.

Default retrieval policy:

```text
processing_revision_mode = latest_completed
```

Selection rules:

- latest completed revision per document version is selected by default;
- failed and in-progress revisions are excluded;
- older completed revisions are excluded unless explicitly requested;
- legacy null-revision chunks are used only when no completed revision exists;
- explicit revision requests are accepted only for completed revisions;
- selection is isolated by organization and document version.

Supported modes:

```text
latest_completed
explicit
legacy_fallback
legacy_only
```

## Retrieval and citation

PostgreSQL FTS remains the mandatory retrieval provider.

Retrieval supports filters for:

- organization;
- collection;
- document record;
- document version;
- content modality;
- evidence role;
- processing revision.

Context and citations preserve:

- document record identifier;
- document version identifier;
- chunk identifier and deterministic key;
- processing revision identifier;
- processing revision selection mode;
- source locator;
- provider traceability for derived visual evidence;
- citation basis.

## Observability

Provider-neutral runtime metrics include:

```text
visual_items_detected
visual_items_enriched
visual_items_skipped
visual_items_failed
visual_items_partial
visual_provider_counts
visual_status_counts
visual_enrichment_duration_ms
visual_chunks_requested
visual_chunks_created
visual_chunks_existing
visual_chunk_indexing_duration_ms
multimodal_processing_revision_id
multimodal_flow_status
```

Flow states:

```text
complete
partial
degraded
empty
not_applicable
```

Metrics use the existing runtime evidence model and do not introduce a separate source of truth.

## Failure behavior

```text
visual provider unavailable
  -> textual ingestion remains valid
  -> visual path reports degraded or not applicable

visual publication failure
  -> failure is observable
  -> textual evidence remains preserved

visual indexing failure
  -> transaction rolls back
  -> failure type and duration are reported

failed processing revision
  -> excluded from default and explicit retrieval
```

## Security and tenancy

Every materialization and retrieval operation is scoped by organization.

Optional provider metadata cannot override:

- organization isolation;
- document classification;
- security policies;
- collection membership;
- application-layer authorization.

## Community and Enterprise boundary

Community may provide:

- local embedded-image extraction;
- deterministic or locally hosted visual providers;
- PostgreSQL materialization and FTS;
- revision selection;
- context and citations;
- baseline runtime metrics.

Enterprise may add:

- managed visual providers;
- GPU scheduling and quotas;
- distributed semantic publication;
- advanced capacity governance;
- enhanced observability and policy controls.

Both editions use the same evidence, revision, chunk and citation contracts.

## Validation baseline


```text
explicit dependency injection = PASSED
PostgreSQL concurrency = PASSED
atomic visual upsert = PASSED
multimodal observability = PASSED
processing revision selection = PASSED
full multimodal chain = PASSED
```

See `docs/validation/sprint-25-11-multimodal-hardening-closure.md`.
