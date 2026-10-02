# ADR 007: Product Editions

## Decision

The product will be structured as Community Edition plus Enterprise Edition.

## Community Edition

Community Edition is based on Core modules and community plugins.

## Enterprise Edition

Enterprise Edition adds commercial extensions and premium capabilities.

## Dependency rule

Core must not depend on Enterprise.

Enterprise may depend on Core.

## Rationale

Separating editions early avoids future rewrites and allows the project to be published as open core later.

## Consequences

Code, documentation, plugins, and deployment templates must respect the product boundary.
