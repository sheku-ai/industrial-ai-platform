# SHEKU — Product Definition

**SHEKU**  
*Knowledge into action.*

SHEKU is a generic, configurable and deployment-neutral governed enterprise knowledge platform for industrial organizations.

It combines industrial document management, governed enterprise knowledge, enterprise search, assistants, conversations, connectors, governance and optional AI services.

It is not a customer implementation and it is not a RAG product.

## What SHEKU does

SHEKU converts enterprise information into governed knowledge that people, applications and AI systems can trust and use.

The product manages the complete path from source information to usable knowledge:

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

The product is useful before AI is enabled. Documents, lifecycle, governed knowledge, PostgreSQL lexical search, organization isolation, security, runtime evidence and audit remain product capabilities without embeddings, a vector database or an LLM.

## Core product proposition

A conventional RAG system optimizes for answering questions over documents:

```text
Document
-> Chunk
-> Embedding
-> Vector Database
-> LLM
-> Answer
```

SHEKU addresses a broader enterprise problem:

```text
Enterprise information
-> governed document lifecycle
-> persisted processing evidence
-> governed knowledge publication
-> authoritative knowledge index
-> enterprise search
-> people / applications / AI
```

The RAG pattern may be used as an optional retrieval capability, but it does not define the product architecture.

## Architectural differentiation

### PostgreSQL is authoritative

PostgreSQL is the authority for platform state, lifecycle state, ownership, organization scope, governed knowledge and runtime evidence.

Object storage contains binary payloads and derived artifacts. Vector stores and semantic indexes are optional and rebuildable.

### Knowledge exists independently of AI

SHEKU owns the knowledge. AI consumes it.

A model provider may change, be disabled or be unavailable without invalidating the governed knowledge already maintained by SHEKU.

### Lifecycle instead of upload-and-index

Documents are governed entities rather than anonymous RAG inputs.

The intended chain is:

```text
Document Registration
-> Document Version
-> Binary Upload
-> Storage Execution
-> Storage Verification
-> Processing
-> Chunking
-> Knowledge Publication
-> PostgreSQL Knowledge Index
-> Enterprise Search
```

### Evidence before flags

Completion and readiness are determined from persisted evidence, not transient memory, caches or convenience booleans when authoritative evidence exists.

A runtime should be able to prove why a stage is complete and what persisted record supports that conclusion.

### Lineage and provenance

Knowledge can be traced back through its originating publication, processing execution, document version and source artifact.

Conceptually:

```text
Answer or Search Result
-> Knowledge Entry
-> Knowledge Publication
-> Processing Evidence
-> Document Version
-> Source Artifact
```

Citations are a user-facing expression of this provenance; lineage is the deeper platform property.

### Enterprise Search is not synonymous with vector search

PostgreSQL Full Text Search is the governed lexical baseline.

Semantic retrieval, embeddings, vector stores, hybrid search and AI reranking are optional extensions.

### Organization isolation is native

Organization isolation applies at backend data and runtime boundaries across documents, knowledge, search, assistants, conversations, permissions and runtime evidence.

It is not a UI-only tenant selector.

### Security governs knowledge consumption

Authorization applies not only to opening a source document but also to whether derived knowledge may participate in search or assistant context.

### Assistant and Conversation are governed runtimes

Assistant definitions, conversations, turns, retrieval, context assembly, provider execution, citations and responses are persisted and auditable runtime concepts rather than a single opaque LLM call.

This supports isolation, idempotency, retries, correlation, history and audit.

### Deployment neutrality

The product model is designed for local, on-premise, hybrid and cloud operation. AI services remain replaceable adapters rather than SHEKU prerequisites.

## What keeps SHEKU out of the "another RAG" category

| Dimension | Typical RAG product | SHEKU |
|---|---|---|
| Document | retrieval input | governed domain entity |
| Lifecycle | upload -> index | register -> version -> store -> verify -> process -> publish -> index |
| State authority | often pipeline/vector state | PostgreSQL |
| Knowledge | derived primarily for retrieval | persisted governed domain |
| Search | semantic/vector centric | PostgreSQL lexical baseline + optional semantic extensions |
| LLM | central requirement | optional consumer |
| Embeddings | core dependency | optional derived capability |
| Vector database | core dependency | optional derived index |
| Lineage | usually citation-level | platform-level provenance |
| Completion | pipeline flags/jobs | persisted authoritative evidence |
| Organization isolation | frequently added around retrieval | product invariant |
| Audit | operational logs | runtime and domain evidence |
| Assistant | primary product | one consumer of governed knowledge |
| External consumers | integrations around chat | Portal, API and future agent/MCP consumers |

## Strategic product position

SHEKU should not compete on the claim "chat with your documents". That capability is increasingly commoditized.

The strategic position is governed enterprise knowledge infrastructure for industrial organizations.

SHEKU should become the trusted knowledge layer used by:

```text
People
Applications
Enterprise Search
Assistants
AI Agents
External integrations
```

The durable competitive asset is the governed knowledge and its lineage, not the selected LLM.
