# SHEKU

**Knowledge into action.**

SHEKU is a generic, configurable and SaaS-capable governed enterprise knowledge platform for industrial organizations, combining document management, enterprise search, assistants, conversations, connectors, governance and optional AI services.

This repository contains a product platform. It is not a customer-specific implementation and it is not a RAG-only product.

## Product position

SHEKU converts enterprise information into governed knowledge that people, applications and AI systems can trust and use.

The platform remains useful without embeddings, a vector database or an LLM.

```text
Configuration
-> Registration
-> Storage
-> Processing
-> Chunking
-> Knowledge Publication
-> Knowledge Index
-> Enterprise Search
-> Assistant
-> Conversation
-> Feedback
-> Audit
```

AI is an optional consumer of governed knowledge, not the authority for that knowledge.

## Release line

```text
Product name: SHEKU
Tagline: Knowledge into action.
Release line: 1.6.0
Stage: PRE-PRODUCTION
PostgreSQL: SOURCE OF TRUTH
AI: OPTIONAL SERVICE LAYER
Enterprise Search baseline: PostgreSQL FTS
Organization isolation: MANDATORY
```


## Licensing

SHEKU follows an open-core model:

- **SHEKU Community / Core:** Apache License 2.0, as defined by [`LICENSE`](LICENSE).
- **SHEKU Enterprise:** separate commercial proprietary license.
- **SHEKU name, tagline and brand assets:** governed separately by [`TRADEMARKS.md`](TRADEMARKS.md).

See [`docs/product/licensing.md`](docs/product/licensing.md) and [`docs/product/edition-strategy.md`](docs/product/edition-strategy.md) for the product and architectural boundaries.

## Installation

For a clean SHEKU 1.6.0 installation:

```bash
git clone https://github.com/sheku-ai/industrial-ai-platform.git
cd industrial-ai-platform
git checkout 1.6.0
./scripts/install-platform.sh
```

The installer performs a non-destructive prerequisite preflight before creating installation state.

See:

- [System Requirements](docs/installation/system-requirements.md)
- [Installation Guide](docs/installation/installation-guide.md)
- [RC validation workflow](docs/installation/local-runtime.md#release-candidate-validation)

## Canonical documentation

Start with [`docs/README.md`](docs/README.md).

| Document | Purpose |
|---|---|
| [`docs/installation/system-requirements.md`](docs/installation/system-requirements.md) | Supported hosts, prerequisites, ports and storage requirements. |
| [`docs/installation/installation-guide.md`](docs/installation/installation-guide.md) | Canonical clean installation and first-run setup. |
| [`docs/product/sheku-product-definition.md`](docs/product/sheku-product-definition.md) | What SHEKU is, how it works and why it is not another RAG platform. |
| [`docs/product/capabilities.md`](docs/product/capabilities.md) | Product capability catalog and optionality boundaries. |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | Canonical architecture, runtime graph and persistence ownership. |
| [`docs/product/licensing.md`](docs/product/licensing.md) | Community/Core, Enterprise and trademark licensing boundaries. |
| [`docs/product/vision/product-vision.md`](docs/product/vision/product-vision.md) | Stable product vision and capability domains. |
| [`docs/deployment/PRODUCTION_READINESS.md`](docs/deployment/PRODUCTION_READINESS.md) | Production-readiness contract. |

## Product principles

1. Product before customer-specific implementation.
2. PostgreSQL is authoritative for configuration, lifecycle state, governed knowledge and runtime evidence.
3. Object storage contains binary payloads and derived artifacts, not lifecycle truth.
4. AI, embeddings, vector databases and external model providers are optional.
5. SHEKU must remain useful without AI.
6. Configuration is preferred over hardcoding.
7. Community and Enterprise remain separable by architecture.
8. Persisted evidence is authoritative; derived flags are not.
9. Organization isolation is mandatory at backend boundaries.
10. Product Acceptance contracts must never be weakened to hide defects.
11. Determinism, idempotency, lineage and auditability are product requirements.
12. AI consumes governed knowledge; it does not own it.

## Why SHEKU is not another RAG

A conventional RAG product generally follows:

```text
Document
-> Chunk
-> Embedding
-> Vector Database
-> LLM
-> Answer
```

SHEKU manages the governed lifecycle before any optional AI retrieval layer:

```text
Document Registration
-> Document Version
-> Binary Upload
-> Storage Verification
-> Processing
-> Knowledge Publication
-> PostgreSQL Knowledge Index
-> Enterprise Search
-> optional AI consumption
```

The durable product asset is governed knowledge with ownership, lineage, authorization and persisted evidence.

## Safety position

```text
Platform PostgreSQL = product state and governed knowledge authority
Identity PostgreSQL = authentication and identity-domain authority
Object storage = source and derived binary payloads
PostgreSQL FTS = governed lexical search baseline
Vector database = optional derived index
Embeddings = optional
AI providers = optional
Organization isolation = mandatory
Production configuration = fail closed
```
