# Assistant Runtime Architecture

## Purpose

The Assistant Runtime provides a persistent, auditable and provider-neutral assistant pipeline for the Industrial AI Platform.

It is a generic platform capability. It must not encode customer-specific organization structures, plant names, site names, fixed roles, fixed document types or fixed business processes.

## Architectural position

The Assistant Runtime sits above governed knowledge and search capabilities.

```text
PostgreSQL Knowledge Index
-> PostgreSQL FTS
-> Enterprise Search
-> Assistant Retrieval
-> Assistant Context
-> Assistant Prompt
-> Assistant LLM Gateway
-> Assistant LLM Runtime Persistence
-> Assistant Citation Verification
-> Assistant Response Runtime
-> Conversation Runtime
-> Chat Runtime Orchestrator
```

PostgreSQL remains the source of truth for platform state, governed knowledge, runtime records and assistant lifecycle state.

AI is an optional service layer. The platform must continue to operate without mandatory LLM, embedding, vector database or external AI provider availability.

## Current runtime chain

```text
Assistant Definition
-> Assistant Session
-> Conversation
-> Conversation Turn                         [user]
-> Assistant Runtime Run
-> Retrieval Plan
-> Retrieval Readiness
-> Enterprise Search
-> Context Package
-> Prompt Package
-> LLM Gateway Plan
-> LLM Runtime Record
-> Raw Provider Output
-> Citation Verification Record
-> Assistant Response Record
-> Conversation Turn                         [assistant]
-> Chat Runtime Orchestrator
```

The current baseline persists raw LLM runtime output separately from final assistant responses, verifies citation references against persisted context evidence, persists the final assistant response, and records conversation history.

## Implemented domains

| Domain | Status | Notes |
| --- | --- | --- |
| Assistant Runtime | Implemented | Metadata/runtime run creation |
| Retrieval Planning | Implemented | Plans search mode and runtime domain |
| Retrieval Readiness | Implemented | Prepares search metadata |
| Enterprise Search | Implemented | Uses PostgreSQL FTS |
| Context Builder | Implemented | Builds ordered evidence package |
| Prompt Assembly | Implemented | Builds prompt package from context |
| LLM Gateway | Implemented | Persists provider and parameter planning |
| LLM Runtime Persistence | Implemented | Persists raw provider result metadata through deterministic local mock validation |
| Citation Verification | Implemented | Validates persisted citation identifiers against persisted context evidence |
| Response Runtime | Implemented | Persists governed final assistant response |
| Conversation Memory | Implemented | Persists conversations and turns |
| Chat Runtime Orchestrator | Implemented | Coordinates existing runtimes into a chat flow |
| Tool Planning | Planned | Tool decision planning only |
| Tool Runtime | Planned | Controlled action stage later |

## Runtime persistence

Each stage emits runtime persistence records. Runtime persistence supports:

- lifecycle traceability;
- smoke validation;
- audit readiness;
- replay metadata;
- operational diagnosis;
- future tenant and policy enforcement.

Runtime persistence is not a substitute for business entities, governed knowledge or final response records. It records execution state, evidence lineage and technical traceability.

## Retrieval boundary

The retrieval path is complete through Context Builder:

```text
Retrieval Plan
-> Retrieval Readiness
-> Enterprise Search
-> Context Package
```

Enterprise Search is backed by PostgreSQL Full Text Search. Semantic search, vector search and Qdrant remain optional derived capabilities and are not the source of truth.

## Prompt boundary

Prompt Assembly creates a persisted prompt package from a context package.

The prompt package contains:

- system prompt;
- assistant instructions;
- assembled governed context;
- citation section;
- size and token estimates;
- metadata required by the LLM Gateway.

Prompt Assembly does not produce a final assistant response and does not call a provider directly.

## LLM Gateway boundary

LLM Gateway Foundation consumes a prompt package and persists a gateway plan.

The gateway plan contains:

- provider metadata;
- model metadata;
- planned parameters;
- readiness flags;
- policy metadata;
- blocked or allowed state.

The gateway does not define knowledge and does not bypass PostgreSQL or Enterprise Search.

## LLM Runtime Persistence boundary

LLM Runtime Persistence consumes an existing gateway plan and persists a raw provider result record.

The runtime record contains:

- assistant runtime linkage;
- prompt package linkage;
- gateway plan linkage;
- provider type and model metadata;
- provider call mode;
- raw output metadata;
- status and duration metadata;
- safety flags showing that no tool, workflow action or autonomous execution occurred.

Current validation uses a deterministic local mock provider path. Real external provider calls remain disabled by default unless explicitly configured and governed.

This stage does not perform:

- citation verification;
- final answer creation;
- conversation memory updates;
- tool invocation;
- workflow action execution;
- autonomous execution.

## Citation Verification boundary

Citation Verification consumes a persisted LLM runtime record and validates citation references against the persisted context package.

The citation verification record contains:

- assistant runtime linkage;
- LLM runtime linkage;
- prompt package linkage;
- context package linkage;
- verification status;
- verified citation count;
- missing citation count;
- invalid citation count;
- verification summary;
- runtime metadata.

The verification is deterministic. It does not use AI, embeddings, vector search, tools, workflow actions or autonomous execution.

## Response Runtime boundary

Assistant Response Runtime consumes a completed citation verification and persisted LLM execution output.

The response record contains:

- citation verification linkage;
- LLM execution linkage;
- prompt package linkage;
- context package linkage;
- assistant linkage;
- response text;
- response metadata;
- ordered citations;
- citation verification counts.

The response stage persists the governed final assistant response. It does not call a model, tool, workflow or external action.

## Conversation Runtime boundary

Conversation Runtime persists:

- conversations;
- conversation turns;
- user messages;
- assistant messages;
- optional assistant runtime trace linkage;
- attached assistant responses.

Conversation state is a product capability independent from AI provider execution.

## Chat Runtime boundary

Chat Runtime Orchestrator coordinates existing runtimes. It does not replace retrieval, search, context, prompt, LLM execution, citation verification, assistant response or conversation runtime.

The chat runtime can return a deterministic no-evidence response when Enterprise Search has no usable results. This keeps the conversation flow usable without fabricating evidence.

## Product constraints

```text
PostgreSQL = source of truth
Enterprise Search = PostgreSQL FTS
AI = optional service layer
LLM Runtime Persistence = raw provider result persistence
Citation Verification = deterministic evidence-reference validation
Assistant Response Runtime = governed final response stage
Conversation Runtime = persisted conversation history
Chat Runtime = orchestration layer over existing runtimes
Embeddings = optional derived capability
Vector database = optional derived index
Qdrant = optional provider framework
Workflows = explicit runtime domain
Tools = explicit controlled runtime domain
```

## Roadmap

```text
```
