# SHEKU Product Capabilities

**Knowledge into action.**

This document is the capability catalog for the SHEKU 1.6.x release line. It describes product capabilities, not sprint history.

## Capability principles

- Core capabilities must remain useful without AI.
- PostgreSQL is authoritative for governed product state and knowledge lifecycle.
- Organization isolation applies across all supported product domains.
- Optional capabilities must not become hidden prerequisites for baseline operation.
- Community and Enterprise boundaries remain architectural, not hardcoded customer variants.

## Capability catalog

| Capability | Baseline | Enterprise extension | AI required | Notes |
|---|---|---|---|---|
| Identity and authentication | Yes | Advanced governance | No | Separate identity authority and governed sessions. |
| Organization management | Yes | Advanced scale/governance | No | Organization isolation is mandatory. |
| Roles and permissions | Yes | Advanced policy administration | No | Authorization enforced at backend boundaries. |
| Document registration | Yes | Advanced governance | No | Governed document entities. |
| Document versioning | Yes | Advanced lifecycle policy | No | Preserves source traceability. |
| Object storage | Yes | Provider/topology extensions | No | Stores payloads; not lifecycle truth. |
| Storage verification | Yes | Advanced operational evidence | No | Persisted evidence before progression. |
| Processing runtime | Yes | Advanced processing strategies | No | Provider-neutral, persisted execution. |
| Chunk persistence | Yes | Advanced strategies | No | Does not require embeddings. |
| Knowledge publication | Yes | Advanced governance | No | Governed knowledge exists independently of AI. |
| Knowledge lineage | Yes | Advanced reporting | No | Traceable to source lifecycle evidence. |
| PostgreSQL knowledge index | Yes | Scale/topology extensions | No | Governed lexical index baseline. |
| Enterprise Search | Yes | Advanced ranking/federation | No | PostgreSQL FTS baseline. |
| Semantic retrieval | Optional | Optional | Embeddings | Derived capability, not source of truth. |
| Vector index | Optional | Optional | Embeddings | Rebuildable derived index. |
| Hybrid retrieval | Optional | Advanced | No/Optional | Combines governed lexical and optional semantic candidates. |
| AI provider configuration | Optional | Advanced governance | Yes | Provider-neutral configuration. |
| Assistant definitions | Supported | Advanced governance | Optional | Assistants consume governed knowledge. |
| Assistant runtime | Supported | Advanced orchestration | Optional | Provider execution is a separable stage. |
| Conversations and turns | Supported | Advanced retention/governance | Optional | Persistent runtime entities. |
| Citation verification | Supported | Advanced policy | Optional | Evidence-governance stage. |
| Feedback and audit | Yes | Advanced analytics | No | Product/runtime evidence remains persisted. |
| Connectors | Supported framework | Expanded connector catalog | No | External sources are adapters, not core assumptions. |
| Operational control plane | Yes | Distributed/advanced operations | No | Coordinates work without replacing domain authority. |
| Deployment portability | Yes | Enterprise topology | No | Local, on-premise, hybrid and cloud-compatible product model. |
| MCP / external agent interface | Planned | Planned | No/Optional | Must expose governed knowledge, not bypass security/runtime boundaries. |
| Platform diagnostics / doctor | Planned | Advanced diagnostics | No | Should resolve readiness from persisted evidence. |
| Versioned runtime contract schemas | Planned hardening | Advanced governance | No | Stable integration and compatibility contracts. |
| Configuration diff/governance | Planned | Advanced | No | Auditable change comparison. |

## Core no-AI product

The baseline SHEKU product is meaningful with AI disabled:

```text
Identity
-> Organization and Authorization
-> Documents
-> Storage
-> Processing
-> Knowledge Publication
-> PostgreSQL Knowledge Index
-> Enterprise Search
-> Audit and Runtime Evidence
```

This is a deliberate product boundary. AI is an enhancement layer, not the condition for the product to exist.

## Optional AI layer

```text
Governed Knowledge
-> Authorized Retrieval
-> Context Assembly
-> Prompt Assembly
-> optional Provider Execution
-> Citation Verification
-> Assistant Response
-> Conversation Persistence
```

Model providers, embeddings and vector infrastructure remain replaceable and optional.

## Extension model

SHEKU can evolve through provider-neutral adapters and strategies:

```text
SHEKU Core
├── Storage adapters
├── Processing adapters
├── Connector adapters
├── Search strategies
├── Embedding providers
├── Vector providers
└── LLM providers
```

New adapters must not introduce customer-specific product architecture or become an alternative source of truth.

## Capability status semantics

A capability must not be declared complete because a UI flag says so. Where authoritative evidence exists, capability state is resolved from persisted runtime/domain evidence.

