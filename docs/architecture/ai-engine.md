# AI Engine Architecture

## Purpose

The AI Engine provides configurable AI capabilities as an optional service layer above SHEKU.

SHEKU must continue to function without AI. AI is optional, configurable, replaceable and never required for baseline document lifecycle, storage readiness, processing, governed knowledge indexing, Enterprise Search or governance capabilities.

## Product responsibility

The AI Engine is responsible for:

- model provider configuration;
- prompt configuration;
- assistant configuration;
- guardrail configuration;
- workflow configuration;
- governed context handoff from the Knowledge Engine;
- response governance;
- evaluation hooks;
- AI-specific audit metadata.

It is not responsible for:

- document registration;
- binary upload execution;
- object storage execution;
- processing execution;
- OCR;
- chunking;
- mandatory retrieval;
- mandatory SHEKU operation.

## Platform entities used

```text
ai.models
ai.prompts
ai.agents
ai.knowledge_sources
ai.guardrails
ai.workflows
documents.collections
security.policies
audit.audit_events
```

Document lifecycle readiness may expose `ai_required=false` and `vector_store_required=false` flags. These flags are part of document and storage readiness contracts; they do not require the AI Engine to be enabled.

## Service boundaries

```text
Serving Layer     receives user request
Security Layer    resolves access context
Knowledge Engine  builds governed context
Assistant Runtime orchestrates assistant pipeline state
AI Engine         handles optional provider-facing and response-governance stages
Audit Layer       records request lifecycle
```

AI must only receive governed context from explicit Knowledge Engine or Assistant Runtime contracts. It must not bypass document lifecycle, storage, processing or security layers.

## Assistant Runtime boundary

The Assistant Runtime owns the persistent assistant pipeline through governed response handling:

```text
Assistant Definition
-> Assistant Session
-> Retrieval Planning
-> Retrieval Readiness
-> Enterprise Search
-> Context Builder
-> Prompt Assembly
-> optional LLM Gateway Plan
-> optional LLM Runtime Record
-> Citation Verification Record
-> Assistant Response Runtime
-> Conversation Runtime
```

Enterprise Search uses PostgreSQL Full Text Search as the governed lexical baseline. Context Builder, Prompt Assembly, provider runtime persistence and Citation Verification operate on governed records, persisted citations and provider-neutral runtime contracts.

The AI Engine becomes relevant only after a governed context and prompt package exist. It must not bypass PostgreSQL, Enterprise Search, governed context assembly or security controls.

## LLM Gateway

The LLM Gateway is the boundary between SHEKU-controlled prompt preparation and provider-facing runtime planning.

It is responsible for:

- provider metadata;
- model metadata;
- planned generation parameters;
- readiness state;
- policy metadata;
- runtime persistence;
- provider-neutral contracts.

It is not responsible for:

- knowledge indexing;
- search ranking;
- context selection;
- citation validation;
- final assistant response assembly;
- tool actions;
- workflow actions.

## LLM Runtime Persistence

LLM Runtime Persistence consumes a gateway plan and stores provider result metadata as a runtime record when provider execution is enabled.

Real provider calls remain disabled by default unless explicitly configured and governed.

The persisted runtime record is an intermediate AI runtime artifact used for traceability, auditability and response governance.

LLM Runtime Persistence records:

- assistant runtime linkage;
- prompt package linkage;
- gateway plan linkage;
- provider type and model metadata;
- provider call mode;
- raw provider output metadata;
- status and duration metadata;
- flags confirming whether tool or workflow execution occurred.

## Citation Verification

Citation Verification consumes persisted provider output when present and persisted context citations.

It is responsible for:

- loading the linked runtime record;
- loading the linked prompt package;
- loading the linked context package;
- validating citation identifiers deterministically;
- persisting verified citation count;
- persisting missing citation count;
- persisting invalid citation count;
- persisting verification summary and metadata.

Citation Verification is an evidence-governance stage. It does not make the provider the authority for knowledge or source provenance.

## Model abstraction

Model configuration must be provider-neutral.

A model is configured through:

- provider;
- model name;
- endpoint;
- runtime configuration;
- status;
- organization scope when applicable.

No model provider is mandatory for SHEKU to operate.

## Agent abstraction

Agents are configurable product entities.

An agent references:

- model;
- prompt;
- knowledge sources;
- guardrails;
- workflow rules;
- runtime configuration.

No role, department, process, document type, organization structure or customer-specific workflow may be hardcoded into an agent.

## Guardrail abstraction

Guardrails are configurable policy-like controls for AI stages.

They may govern:

- allowed sources;
- blocked actions;
- citation requirements;
- response format;
- safety filters;
- escalation behavior;
- confidence handling.

## Non-AI mode

When AI is disabled or unavailable, SHEKU must still support:

- document management configuration;
- document registration;
- document version planning;
- binary upload readiness;
- storage provider readiness;
- processing readiness;
- governance and audit;
- governed lexical retrieval;
- Enterprise Search over PostgreSQL FTS.

## Current boundary

The active architecture includes governed prompt assembly, optional provider planning/execution, runtime persistence, citation verification, assistant response persistence and conversation persistence as separate runtime concerns.

