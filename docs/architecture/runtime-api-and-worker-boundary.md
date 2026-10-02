# Runtime API and Worker Boundary

## Purpose


The runtime is a generic platform capability. It does not assume a fixed industry, organization model, document format, connector, provider, model or workflow.

## Runtime API Namespace

Persistent technical execution is exposed under:

```text
/api/runtime
```

It is intentionally separate from:

```text
/api/ai/runtime
```

`/api/runtime` manages durable asynchronous execution state. `/api/ai/runtime` resolves optional AI runtime configuration and fallback behavior.

## API Surface

```text
POST /api/runtime/executions
GET  /api/runtime/executions
GET  /api/runtime/executions/{execution_id}
GET  /api/runtime/executions/{execution_id}/attempts
GET  /api/runtime/executions/{execution_id}/events
GET  /api/runtime/executions/{execution_id}/artifacts
POST /api/runtime/executions/{execution_id}/cancel
POST /api/runtime/executions/{execution_id}/retry
```

## Tenant Boundary

The API does not trust `organization_id` from arbitrary request bodies.

Current internal request context:

```text
X-Organization-ID
X-Actor-Reference
X-Runtime-Admin
```

These are interim trusted headers. They must be replaced or populated exclusively by validated authentication and authorization middleware before external exposure.

Every repository lookup remains tenant-scoped even when an execution identifier is globally unique.

## Transaction Ownership

```text
API route or worker host
    -> application service
        -> repository
```

Rules:

- routes and worker hosts own commit and rollback;
- lifecycle services own state-transition semantics;
- repositories flush but do not commit;
- adapters do not access repositories directly;
- execution state and lifecycle event append occur within one transaction.

Long-running extraction, OCR, parsing, chunking and external artifact publication must not hold an open PostgreSQL transaction. Productive workers use short checkpoint transactions and revalidate tenant, execution, attempt, lease and cancellation state before each durable mutation.

## Worker Boundary

The provider-neutral worker contract consists of:

```text
RuntimeExecutionAdapter
RuntimeAdapterRegistry
RuntimeWorkerService
RuntimeHeartbeat
RuntimeWorkItem
RuntimeAdapterResult
```

Lifecycle flow:

```text
claim
-> lease token
-> start
-> adapter execute
-> optional heartbeat
-> succeed or fail
```

A worker cannot mutate an execution without the current non-expired lease token.

## Adapter Contract

An adapter is selected by `execution_type` and receives a generic work item containing:

- tenant identifier;
- execution identifier;
- execution type;
- subject type and identifier;
- attempt identifier and number;
- lease token;
- input payload;
- policy snapshot.

Adapters return controlled outputs and metrics. Artifact publication and domain-specific outputs must use explicit platform services rather than direct runtime-table mutation.


```python
class RuntimeExecutionAdapter(Protocol):
    execution_type: str

    def execute(
        self,
        item: RuntimeWorkItem,
        context: RuntimeExecutionContext,
    ) -> RuntimeAdapterResult:
        ...
```

```python
class RuntimeExecutionContext(Protocol):
    heartbeat: RuntimeHeartbeat
    cancellation: RuntimeCancellation
    stages: RuntimeStageReporter
    artifacts: RuntimeArtifactPublisher
```

The execution context is capability-limited. It must not expose SQLAlchemy sessions, repositories, commit, rollback or unrestricted lifecycle operations.

## Ingestion Specialization

Productive ingestion uses one runtime execution type:

```text
execution_type = document.ingestion
subject_type = document_version
subject_id = document_version_id
```

The runtime adapter coordinates an ingestion pipeline. Format-specific adapters remain narrower extraction components and do not become runtime workers themselves.

```text
RuntimeWorkerService
    -> DocumentIngestionRuntimeAdapter
        -> IngestionPipelineCoordinator
            -> SourceAcquisitionService
            -> IngestionAdapterResolver
            -> IngestionAdapter
            -> NormalizationService
            -> ChunkingService
            -> QualityService
            -> DocumentPersistenceService
            -> ArtifactPublicationService
            -> LexicalIndexService
            -> OptionalKnowledgePublicationService
```

## Ingestion Adapter Rules

An ingestion adapter:

- validates and extracts source content;
- declares capabilities;
- returns normalized intermediate content units and proposed artifacts;
- does not commit or roll back;
- does not write runtime tables;
- does not persist document chunks;
- does not publish artifacts directly;
- does not define business metadata;
- does not require LLMs, embeddings or vector databases;
- does not own execution retry policy.

Adapter selection must be configuration-driven. Filename extension may be one signal but cannot be the business routing contract.

Resolution may evaluate:

```text
declared media type
detected media type
content signature
container format
pipeline profile
enabled adapter configuration
organization policy
adapter priority
deployment edition
dependency availability
```

The in-memory adapter registry remains a technical instantiation mechanism. Persistent platform configuration determines enabled capabilities and selection priority.

## Stages and Events

Canonical ingestion stages:

```text
source.acquire
source.validate
adapter.resolve
content.extract
content.normalize
content.chunk
content.quality_filter
content.persist
artifact.publish
lexical.index
embedding.generate
vector.publish
execution.finalize
```

Optional AI and vector stages may be skipped, disabled, not configured or fail non-blockingly according to policy.

High-level runtime events:

```text
stage.started
stage.completed
stage.skipped
stage.failed
artifact.registered
cancellation.observed
cleanup.completed
```

Detailed diagnostics belong in structured logs, metrics or bounded diagnostic artifacts rather than unbounded event payloads.

## Cancellation

Cancellation is cooperative and distinct from failure.

The execution context must provide cancellation observation without exposing direct runtime mutation.

Workers check cancellation:

- before and after source acquisition;
- between extraction units;
- during persistence batches;
- before artifact publication;
- before lexical or optional semantic publication.

Compatibility subprocess adapters must support timeout, terminate, grace period, kill and workspace cleanup.

## Failure Rules

- missing adapter results in `adapter_not_configured`;
- adapter exceptions are sanitized before persistence;
- stale or expired leases are rejected;
- closed attempts cannot reopen;
- terminal executions cannot reactivate;
- partial lifecycle failures roll back execution state and event append together;
- cancellation is not persisted as a generic adapter failure;
- optional embedding or vector failure must not automatically invalidate successfully persisted ingestion output.

Persisted errors contain safe codes, safe messages, stage and retryability. Stack traces, secrets, DSNs, sensitive paths and complete source content are not persisted in runtime errors.

## Artifact Boundary

Runtime artifacts are generic references containing type, storage URI, media type, checksum, size, metadata and status.

Adapters propose outputs. A platform artifact service publishes and registers them.

Artifact publication must be idempotent by logical identity and checksum. Productive code must not derive storage paths directly from untrusted metadata.

## Domain Compatibility

The runtime can be linked non-destructively to:

```text
documents.ingestion_jobs
documents.indexing_jobs
connectors.connector_runs
```

Domain records retain domain-state ownership. Runtime records retain technical execution-state ownership. No cross-schema synchronization trigger is used.

For ingestion:

```text
runtime.executions.id
    <- documents.ingestion_jobs.runtime_execution_id
```

Runtime owns scheduling, attempts, leases, retries, cancellation and technical metrics.

The documents domain owns pipeline profile, adapter resolution snapshot, processing revision, chunks, domain result and publication state.

## Retry and Idempotency

Runtime owns execution retries, backoff, lease expiration and dead-letter behavior.

Adapters do not implement an independent scheduler.

Chunk and artifact persistence must be deterministic so a retry can recognize already-completed equivalent work.

Vector publication occurs only after PostgreSQL chunk persistence commits and is treated as optional derived processing.

## Provider Execution

Provider execution remains disabled.

The worker boundary can host future adapters, but no external inference, model, connector or extractor is enabled merely by registering runtime persistence or documenting an adapter contract.

Productive ingestion implementation must not activate historical subprocess execution until a later work package explicitly introduces and validates a controlled compatibility adapter.

## Community and Enterprise

Community and Enterprise share the same runtime and adapter contracts.

Community may provide local or S3-compatible source acquisition, basic extraction adapters, PostgreSQL persistence, lexical indexing and local optional OCR.

Enterprise may add advanced scanning, DLP, connector-managed acquisition, external OCR, distributed queues, autoscaling, quotas, encryption-key integration and advanced policy enforcement.

Enterprise capability does not redefine runtime or document ownership.

## No-AI Guarantee

The mandatory ingestion path is:

```text
source acquisition
validation
extraction
normalization
chunking
quality filtering
PostgreSQL persistence
artifact publication
PostgreSQL lexical indexing
success
```

Optional processing is separate:

```text
embedding generation
vector publication
LLM-assisted enrichment
```

The mandatory path must not initialize or require an inference provider, embedding model or vector database.

## Deferred Work

```text
JWT-backed tenant and permission context
productive ingestion adapter implementation
persistent adapter and pipeline configuration
distributed worker scheduling
streaming execution
capacity and quota governance
bulk operational actions
advanced observability and metrics
```
