# SHEKU Deployment

Deployment documentation for the SHEKU 1.6.x release line.

SHEKU is deployment-neutral at the product-model level. Supported topologies may be local, on-premise, hybrid or cloud-based, but deployment choices must not alter the product's authority and isolation rules.

## Invariants across topologies

```text
Platform PostgreSQL = authoritative product and knowledge state
Identity PostgreSQL = authoritative identity and session state
Object storage = source and derived binary payloads
PostgreSQL FTS = governed lexical search baseline
AI providers = optional
Embeddings/vector infrastructure = optional
Organization isolation = mandatory
```

## Production readiness

A running deployment is not automatically production-ready.

Use `PRODUCTION_READINESS.md` as the stable acceptance contract for production classification.

Concrete topology-specific installation procedures belong under `docs/installation/` or explicit deployment guides once validated. Development-only workstation history does not belong in the active deployment documentation.
