# SHEKU Document Model

SHEKU governs enterprise documents as configurable domain entities rather than treating files as anonymous retrieval inputs.

## Logical model

```text
Document Type
-> Metadata Schema
-> Document
-> Document Version
-> Source Artifact
-> Storage Evidence
-> Processing Evidence
-> Knowledge Publication
```

## Product rules

- Document types and taxonomies are configurable.
- Metadata schemas and fields are configurable.
- Lifecycle states are product configuration or governed domain state, not customer-specific hardcodes.
- Security classification is configurable and participates in authorization and knowledge eligibility.
- Document versions preserve source lineage and lifecycle history.
- Collections may group documents or knowledge without becoming ownership authority.
- A document remains meaningful without embeddings, vector storage or AI.
- Derived knowledge must remain traceable to its source document/version and persisted processing evidence.

## Ownership

PostgreSQL is authoritative for document identity, versioning, lifecycle state, organization scope, metadata and runtime evidence.

Object storage contains source and derived binary payloads. Object existence alone does not prove document lifecycle completion.

## Runtime relationship

```text
Document Registration
-> Document Version
-> Binary Upload
-> Storage Verification
-> Processing
-> Chunking
-> Knowledge Publication
-> PostgreSQL Knowledge Index
-> Enterprise Search
```

The canonical cross-domain architecture is defined in `docs/architecture/overview.md`.
