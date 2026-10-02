# Product Vision — SHEKU

**Knowledge into action.**

## Product definition

SHEKU is a generic, configurable and deployment-neutral governed enterprise knowledge platform for industrial organizations, combining documents, enterprise search, connectors, governance and optional AI-assisted capabilities.

It is a product platform, not a customer implementation and not a RAG-only product.

SHEKU converts enterprise information into governed knowledge that people, applications and AI systems can trust and use.

It must not assume a specific company, plant, site, asset type, department, country, document taxonomy, metadata model, workflow, provider, AI model or organizational hierarchy. Those concepts may exist as tenant configuration, templates or examples, but never as fixed product architecture.

## Product outcomes

SHEKU enables organizations to:

- reduce time spent locating reliable information;
- preserve and govern organizational knowledge;
- manage documents and derived knowledge consistently;
- expose auditable, source-aware search and assistant experiences;
- operate locally, on-premise, in hybrid environments or in cloud deployments;
- adopt AI incrementally without making it operationally mandatory;
- maintain clear organization, security and compliance boundaries;
- extend the product without rewriting its core;
- make governed knowledge reusable by people, applications and future external agents.

## Product capability domains

### Platform Core

- organization and tenant model;
- configurable organization nodes and relationships;
- authentication and authorization;
- policies and audit;
- persistent runtime execution;
- operational control plane;
- configuration and feature management;
- Community and Enterprise edition boundaries.

### Documents and Knowledge

- document records and versions;
- configurable document types and metadata;
- source artifacts and storage evidence;
- deterministic processing and chunk persistence;
- governed knowledge publication;
- PostgreSQL knowledge index;
- lexical enterprise search;
- citations, provenance and lineage;
- retention, classification and feedback signals.

### Connectors and Integration

- connector type registry;
- configurable connector instances;
- connector execution history;
- provider-neutral adapter boundaries;
- generic enterprise and industrial source integration;
- artifact and object-store integration.

### Operational Control Plane

- persistent operational jobs and schedules;
- registered platform operations;
- auditable run history;
- bounded reconciliation and recovery workflows;
- administrator health and work queues;
- separable Enterprise extensions for distributed coordination and advanced integrations.

The control plane coordinates work. It does not replace runtime, document or knowledge lifecycle authority.

### Enterprise Search

Enterprise Search is a product capability independent from AI.

PostgreSQL Full Text Search is the governed lexical baseline. Optional semantic retrieval, embeddings, vector stores, hybrid retrieval and reranking extend the baseline without becoming the authority for knowledge.

### AI Service Layer

- optional model and provider registries;
- prompts and guardrails;
- optional embeddings;
- optional vector indexes;
- optional hybrid retrieval;
- source-aware assistants;
- deterministic no-AI fallback;
- provider-neutral execution boundaries.

AI is not the product core. AI consumes governed knowledge maintained by SHEKU.

## Product principles

1. Product first.
2. Configuration over hardcoding.
3. PostgreSQL is the source of truth.
4. AI is optional.
5. Organization isolation by construction.
6. Community and Enterprise remain separable.
7. Implementation assets do not define architecture.
8. Maintainability over shortcuts.
9. Persisted evidence before derived flags.
10. Determinism and idempotency before duplication.
11. Lineage and auditability are product requirements.
12. Deployment neutrality.
13. Controlled evolution through explicit contracts.
14. No arbitrary runtime code configuration.

## Knowledge architecture principle

The durable asset of SHEKU is governed knowledge, not a particular search engine or LLM.

```text
Enterprise Information
-> Documents and Sources
-> Storage Evidence
-> Processing Evidence
-> Knowledge Publication
-> Governed Knowledge Index
-> Enterprise Search
-> People / Applications / AI
```

Knowledge must remain usable when AI, embeddings and vector infrastructure are disabled.

## Product experience

SHEKU should progressively provide:

- administration through the portal;
- equivalent configuration through APIs;
- clear runtime and job visibility;
- transparent disabled and degraded states;
- no hidden provider execution;
- actionable errors without exposing secrets;
- consistent behavior across deployment models;
- explainable source, citation and lineage paths.

## Product architecture direction

SHEKU separates:

```text
control plane
configuration
security and governance
domain records
runtime execution
workers and adapters
object storage
knowledge persistence
lexical retrieval
optional semantic retrieval
optional AI execution
portal and APIs
future external agent interfaces
```

Domain records describe requests and business results. Runtime records describe technical execution. Workers execute through controlled lifecycle services. Providers remain replaceable adapters.

## Strategic positioning

SHEKU should not position itself primarily as "chat with your documents".

The target category is governed enterprise knowledge infrastructure for industrial organizations.

SHEKU's value is the trustworthy knowledge layer that can serve users, applications, enterprise search, assistants and future AI agents.

## Related canonical documents

- `docs/product/sheku-product-definition.md` — detailed differentiation and product definition.
- `docs/product/capabilities.md` — capability catalog and optionality boundaries.
- `docs/architecture/overview.md` — canonical runtime architecture and persistence boundaries.
- `docs/architecture/code-stability-and-change-policy.md` — code stability and change rules.
