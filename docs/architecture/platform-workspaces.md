# Platform Workspaces

## Overview

Platform Workspaces are the primary functional areas of the Admin Portal. They expose the product through normalized Workspace Runtime endpoints backed by PostgreSQL.

```text
User
-> Admin Portal
-> Workspace
-> Runtime API
-> Workspace Runtime
-> Domain Runtime
-> PostgreSQL
```

## Implemented workspaces

```text
Platform Home
Administration Workspace
Document Workspace
Knowledge Workspace
Search and Discovery Center
Assistant Experience Workspace
AI Studio
Model and Provider Center
Connector Workspace
Operations Center
Governance Center
Security Center
Workflow Studio
Scheduler and Background Services Center
Reporting and Analytics Center
Enterprise API and Integration Center
Production Readiness Center
Product Integration Review
```

## Workspace catalogue

### Platform Home

Entry point for platform health, readiness, recommendations and navigation.

Primary runtime:

```text
GET /api/platform/dashboard/runtime
```

### Administration Workspace

Governed view of organizations, hierarchy, security configuration, document configuration, knowledge configuration, AI configuration and platform capabilities.

Primary runtime:

```text
GET /api/platform/administration/runtime
```

### Document Workspace

Document lifecycle view from registration through storage, processing, chunking, knowledge publication and Enterprise Search readiness.

Primary runtime:

```text
GET /api/documents/workspace/runtime
```

### Knowledge Workspace

Knowledge collections, sources, documents, chunks, indexing state and Enterprise Search readiness.

Primary runtime:

```text
GET /api/knowledge/workspace/runtime
```

### Search and Discovery Center

Governed discovery layer for Enterprise Search, knowledge coverage, documents, chunks, citations, evidence and search diagnostics.

Primary runtime:

```text
GET /api/search/discovery/runtime
```

### Assistant Experience Workspace

Assistant definitions, conversations, retrieval readiness, citations, runtime execution, feedback and diagnostics.

Primary runtime:

```text
GET /api/assistants/workspace/runtime
```

### AI Studio

Governed visibility over models, prompts, guardrails, workflows, assistants, providers and AI readiness without requiring live AI execution.

Primary runtime:

```text
GET /api/ai/studio/runtime
```

### Model and Provider Center

Secret-safe governance view over model inventory, provider inventory, gateway readiness, capabilities, assistant model usage, prompt and guardrail relationships, optional AI status and configuration diagnostics.

This workspace does not execute models, call providers, test credentials, generate embeddings or query Qdrant.

Primary runtime:

```text
GET /api/models/providers/center/runtime
```

### Connector Workspace

Connector inventory, configurations, run history, ingestion impact, diagnostics and audit traceability.

Primary runtime:

```text
GET /api/connectors/workspace/runtime
```

### Operations Center

Runtime persistence, lifecycle activity, processing, workers, knowledge, search, assistants, connectors, feedback, audit and operational diagnostics.

Primary runtime:

```text
GET /api/platform/operations/center/runtime
```

### Governance Center

Audit, feedback, classification, retention, policy readiness, lineage, runtime evidence, compliance readiness and governance diagnostics.

Primary runtime:

```text
GET /api/platform/governance/center/runtime
```

### Security Center

Security posture, roles, permissions, policies, role assignments, effective permissions, scopes, access diagnostics, audit traceability and Reference Tenant security state.

Primary runtime:

```text
GET /api/security/center/runtime
```

### Workflow Studio

Governed visibility over platform workflows, runtime evidence, lifecycle dependencies, readiness, diagnostics, pending capabilities and workflow health without executing workflow actions.

Primary runtime:

```text
GET /api/workflows/studio/runtime
```

### Scheduler and Background Services Center

Read-only operational control-plane view for scheduler jobs, scheduler runs, worker inventory, lease visibility, retry candidates, runtime executions, background pipeline readiness and operational diagnostics.

This workspace does not execute schedulers, trigger workers, retry jobs, manipulate queues, execute connectors, call providers or mutate runtime state.

Primary runtime:

```text
GET /api/scheduler/background-services/center/runtime
```

### Reporting and Analytics Center

Read-only executive and operational analytics workspace for product KPIs, document metrics, knowledge metrics, search metrics, assistant usage, connector activity, feedback trends, audit trends, security posture, workflow readiness, scheduler readiness, model/provider readiness and product-readiness trends.

This workspace consumes existing runtime evidence only. It is not a BI engine, reporting scheduler or data warehouse.

Primary runtime:

```text
GET /api/reporting/analytics/center/runtime
```

### Enterprise API and Integration Center

Read-only governance workspace for platform API inventory, runtime endpoint catalog, API groups, authentication and authorization readiness, security scopes, JWT readiness, service endpoints, connector integrations, webhook and event inventory, integration diagnostics and Reference Tenant integration readiness.

This workspace is not an API gateway, API management platform, OAuth server or webhook executor. It does not execute APIs, run webhooks, execute connectors, call providers or perform external calls.

Primary runtime:

```text
GET /api/enterprise/api-integration/center/runtime
```

### Production Readiness Center

Read-only production readiness assessment workspace for platform baseline, runtime readiness, knowledge readiness, search readiness, assistant readiness, workflow readiness, scheduler readiness, connector readiness, security readiness, governance readiness, API readiness, storage readiness, Reference Tenant readiness, operational diagnostics, blockers, warnings, recommendations and production candidate status.

This workspace is not a deployment engine, CI/CD pipeline, Kubernetes controller or DevOps tool. It does not deploy infrastructure, execute workers, run schedulers, call providers, execute AI or mutate runtime state.

Primary runtime:

```text
GET /api/production/readiness/center/runtime
```

### Product Integration Review

Product-wide validation layer and Release Candidate gate.

Primary runtime:

```text
GET /api/platform/product/integration/runtime
```

## Cross-workspace principles

All workspaces:

- consume normalized runtime contracts;
- reuse existing domain runtimes;
- are PostgreSQL-backed;
- expose readiness and diagnostics;
- avoid customer-specific assumptions;
- avoid side effects unless explicitly intended;
- keep AI optional;
- preserve a consistent user experience.

## Production hardening principles

The following rules apply to all workspace runtimes:

- A top-level workspace must not rebuild other top-level workspaces unless the dependency is explicitly justified.
- Workspace composition should consume lower-level runtime evidence, focused helpers or normalized summaries.
- Circular and recursive workspace aggregation is prohibited.
- Expensive catalog generation, repository queries and calculations should not be repeated within the same request path.
- Product-level workspaces remain read-only unless a governed mutation contract is explicitly designed.
- Public response contracts must remain stable during hardening and normalization.
- Runtime flags must consistently expose PostgreSQL source-of-truth, side-effect, external-call, LLM and Qdrant behavior.
- Optional or evidence-pending domains may degrade observability without blocking the product candidate unless explicitly classified as required.


## Expansion rule

New capabilities should extend existing workspaces before introducing new navigation areas. No new product capability should be introduced before the Release Candidate unless it resolves a confirmed release blocker.
