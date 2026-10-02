# SHEKU Edition Strategy

## Purpose

SHEKU keeps Community and Enterprise separable from the architecture without allowing edition packaging to redefine product truth.

This document defines the architectural boundary between editions. Licensing policy is documented separately in `docs/product/licensing.md`.

## Architectural dependency rule

```text
SHEKU Core / Community-capable boundary
        ↑
        │ may be extended by
        │
SHEKU Enterprise extensions
```

Core must never require Enterprise modules to provide its documented baseline capabilities.

Enterprise may depend on and extend Core.

## Baseline principle

The reusable SHEKU core must preserve the product invariants:

- PostgreSQL as authoritative product and knowledge state;
- organization isolation;
- document lifecycle;
- processing and governed knowledge publication;
- PostgreSQL FTS Enterprise Search baseline;
- persisted runtime evidence and auditability;
- provider-neutral extension boundaries;
- AI, embeddings and vector databases as optional capabilities.

An edition decision must not make AI mandatory for the core product.

## Enterprise extension principle

Enterprise extensions may add capabilities required for larger-scale, regulated or commercially supported deployments, for example advanced governance, operational scale, integration, deployment or administration capabilities.

The exact Enterprise capability catalog is a product/release decision. It must not be inferred from historical planning documents.

## Packaging rule

Edition packaging must preserve clean dependency direction and must not create two divergent product architectures.

Shared domain contracts and lifecycle semantics remain SHEKU contracts. Enterprise extensions integrate through supported boundaries rather than fork the core runtime.

## Licensing rule

The approved licensing model is:

- **SHEKU Community / Core:** Apache License 2.0;
- **SHEKU Enterprise:** separate commercial proprietary license;
- **SHEKU name, tagline and brand assets:** governed separately by the repository trademark policy.

The repository `LICENSE` file is authoritative for Apache-licensed Community/Core distribution. `docs/product/licensing.md` defines the product licensing model and `TRADEMARKS.md` defines brand-use boundaries.

Enterprise components must be explicitly identifiable in packaging and must not be represented as Apache-licensed unless they are intentionally released under that license.

## Documentation rule

Do not maintain duplicated Community and Enterprise feature wish-lists across architecture/vision documents. When edition-specific capabilities are formally approved, record them in `docs/product/capabilities.md` and the applicable release documentation.
