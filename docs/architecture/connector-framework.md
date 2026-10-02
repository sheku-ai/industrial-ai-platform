# SHEKU Connector Framework

The connector framework allows SHEKU to ingest or synchronize external enterprise sources without hardcoding customer or vendor assumptions into the product core.

## Architectural role

A connector is an adapter around a stable SHEKU integration contract. It is not a new source of product truth and it must not bypass organization, security, document or knowledge lifecycle boundaries.

Conceptually:

```text
External Source
-> Connector Adapter
-> Normalized Source Metadata
-> Governed Registration / Ingestion Runtime
-> Documents / Knowledge Lifecycle
```

## Connector responsibilities

Depending on source capabilities, an adapter may provide:

- connectivity validation;
- source discovery;
- full or incremental synchronization;
- metadata mapping;
- permission mapping;
- source identity and change tracking;
- execution status and error reporting;
- lineage back to the originating external record.

The concrete interface may evolve with runtime contracts. Documentation must not prescribe vendor-specific product behavior.

## Product rules

- Connector instances are configurable.
- Credentials are referenced through governed secret/configuration boundaries rather than embedded in connector definitions.
- Connector execution must preserve organization isolation.
- External source permissions must be mapped explicitly where they affect knowledge eligibility.
- Synchronization must be idempotent where source identity and change evidence permit it.
- Connector execution history must be auditable.
- A connector must not write directly into downstream knowledge indexes while bypassing governed lifecycle stages.
- Vendor-specific adapters remain replaceable extensions.

## Extension boundary

```text
SHEKU Core
└── Connector Contract
    ├── Enterprise content adapters
    ├── Database/data-source adapters
    ├── API adapters
    └── Domain-specific adapters
```

Specific supported adapters belong in installation/integration or release documentation when implemented. They do not define the architecture itself.

## Relationship to AI

Connectors do not require AI. AI-assisted extraction or enrichment may exist as optional processing stages after governed source registration, but connector availability and baseline ingestion must not depend on an LLM unless explicitly configured by the organization.

See `docs/architecture/overview.md` for the canonical runtime and persistence boundaries.
