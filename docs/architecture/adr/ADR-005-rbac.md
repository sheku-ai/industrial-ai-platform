# ADR 005: RBAC and Scope Inheritance

## Decision

Use role based access control with scope inheritance.

## Context

Users need access by company, area, department, plant, system, collection, or document type.

## Rationale

RBAC is understandable for administrators and scope inheritance reduces repeated manual configuration.

## Consequences

Access checks must evaluate role, permission, scope, and inheritance policy.
