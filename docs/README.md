# SHEKU Documentation

Maintained product documentation for the 1.6.0 release line.

**SHEKU — Knowledge into action.**

## Start here

1. [`product/sheku-product-definition.md`](product/sheku-product-definition.md) — what SHEKU is, how it works and what differentiates it from RAG-centric products.
2. [`installation/system-requirements.md`](installation/system-requirements.md) — certified installation platforms, host prerequisites, ports and storage requirements.
3. [`installation/installation-guide.md`](installation/installation-guide.md) — canonical clean-install and first-run procedure.
4. [`installation/local-runtime.md#release-candidate-validation`](installation/local-runtime.md#release-candidate-validation) — local Release Candidate validation workflow.
5. [`product/capabilities.md`](product/capabilities.md) — product capability catalog and optionality boundaries.
6. [`architecture/overview.md`](architecture/overview.md) — canonical runtime architecture, persistence ownership and extension boundaries.
7. [`product/licensing.md`](product/licensing.md) — Community/Core, Enterprise and trademark licensing boundaries.
9. [`product/vision/product-vision.md`](product/vision/product-vision.md) — stable product vision.
10. [`deployment/PRODUCTION_READINESS.md`](deployment/PRODUCTION_READINESS.md) — production-readiness requirements.

## Documentation structure

- `architecture/` — canonical product architecture, persistence, runtime design, security boundaries and architectural decisions.
- `installation/` — system requirements, installation, bootstrap, first-run and environment setup.
- `administration/` — SHEKU administration, organization, security and governed configuration.
- `operations/` — supported runbooks, health contracts, migrations, resilience and runtime validation.
- `api/` — API contracts and integration interfaces.
- `product/` — product definition, capability catalog, differentiation, edition and licensing strategy, release information and product direction.
- `deployment/` — deployment and production-readiness documentation.
- `troubleshooting/` — supported troubleshooting guidance.

## Licensing and brand

SHEKU Community/Core is distributed under Apache License 2.0. SHEKU Enterprise uses a separate commercial proprietary license. The SHEKU name, tagline and brand assets are governed separately from the source-code license.

Repository-level terms are maintained in `LICENSE` and `TRADEMARKS.md`.

## Documentation policy

The 1.6.0 release line contains documentation required to understand, install, operate, administer, integrate and evolve SHEKU as a functional product.

Historical sprint, backlog, temporary implementation planning, agent prompts and development working documents are intentionally excluded. Their history remains available through Git and the frozen `older` branch.

Product documentation must not describe obsolete implementation stages as current architecture.

Mutable sprint status must not be embedded in stable architecture or vision documents. Current gaps are expressed as product capabilities still requiring integration or stabilization, not as historical task logs.

Architecture documents must describe implemented or approved product boundaries. Speculative feature stubs do not belong in the active architecture tree.

## Product invariants

Documentation must preserve these architectural truths:

```text
PostgreSQL = authoritative product state and governed knowledge
Identity PostgreSQL = authentication and identity-domain authority
Object storage = binary payloads and derived artifacts
Enterprise Search = PostgreSQL FTS baseline
Embeddings = optional
Vector database = optional
AI = optional service layer
Organization isolation = mandatory
Persisted evidence > derived flags
Determinism + idempotency + lineage + auditability = required
```

If a document contradicts these invariants, duplicates a canonical document without adding a durable contract, or describes a superseded foundation stage, it must be corrected or removed from the active release documentation.
