# ADR 004: Plugin Framework

## Decision

Use a plugin based connector framework.

## Context

The platform must integrate with different document repositories, enterprise systems, and industrial systems.

## Rationale

Plugins allow integrations to evolve independently from the core platform.

## Consequences

Connectors must follow a clear contract and should not modify core services directly.
