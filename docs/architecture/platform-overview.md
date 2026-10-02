# Platform Overview

The platform is a modular industrial AI system for knowledge management, document governance, search, and AI-assisted operations.

## Logical flow

```text
Organization Service
  -> Document Service
  -> Access Service
  -> Knowledge Service
  -> AI Runtime
  -> Connector Framework
```

## Main components

- Admin Portal: web control plane.
- API layer: backend entry point.
- Organization Service: companies, areas, departments, sites, systems, assets.
- Document Service: document types, metadata, versions, collections.
- Access Service: users, roles, permissions, scopes.
- Knowledge Service: chunks, embeddings, semantic search, citations.
- AI Runtime: model providers, prompts, agents, conversations, evaluations.
- Connector Framework: external data and document integrations.

## Design principles

- Modular services.
- Dynamic configuration instead of hard-coded customer structures.
- Local and hybrid AI execution.
- Strict separation between product core and customer-specific packs.
