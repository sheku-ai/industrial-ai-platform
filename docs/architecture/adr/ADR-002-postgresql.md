# ADR 002: PostgreSQL

## Decision

Use PostgreSQL as the primary relational database.

## Context

The platform requires strong relational modeling, JSON metadata, auditability, and future vector support.

## Rationale

PostgreSQL supports relational data, JSONB, indexing, extensions, and operational maturity.

## Consequences

Service schemas should be migration based and compatible with PostgreSQL.
