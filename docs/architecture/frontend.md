# Frontend Architecture

## Current Position

The Admin Portal is the primary user experience for the Industrial AI Platform. It is organized around product workspaces rather than isolated pages.

```text
User
→ Admin Portal (Next.js)
→ Workspace Component
→ Runtime API Client
→ Workspace Runtime Endpoint
→ Domain Runtime
→ PostgreSQL
```

## Frontend Principles

- Every product area is implemented as a Workspace.
- Workspace components consume normalized runtime contracts.
- Business logic remains in backend runtimes.
- The frontend is responsible for presentation, navigation and interaction only.
- No mock data in production workspaces.
- No customer-specific assumptions.

## Implemented Workspaces

```text
Platform Home
Platform Dashboard
Administration Workspace
Operations Center
Document Workspace
Knowledge Workspace
Assistant Experience Workspace
AI Studio
Connector Workspace
Governance Center
```

## Runtime Integration

Each workspace follows the same pattern:

```text
Page
→ Workspace Component
→ API Client
→ Runtime Endpoint
→ Normalized Response
→ UI
```

This ensures a consistent user experience while allowing backend runtimes to evolve independently.

## Layer Responsibilities

### Application Layer

The Next.js application provides routing, layout composition and navigation between product workspaces. It must not contain business orchestration.

### Workspace Components

Workspace components render normalized runtime data received from backend workspace endpoints. They are responsible for presentation, user interaction and composition of reusable UI elements.

### API Client Layer

Each workspace has a dedicated API client responsible for communicating with its runtime endpoint. API clients should encapsulate HTTP details and expose typed methods to the UI.

### Layout and Navigation

The global layout provides consistent navigation across all product workspaces. Navigation reflects product capabilities rather than technical services or implementation details.

## UI Design Rules

- All workspaces follow a consistent visual language.
- Summary cards appear before detailed sections.
- Diagnostics and readiness are always visible.
- Empty states must clearly indicate missing capabilities.
- Runtime-driven content must be distinguished from static descriptive text.
- No secrets or sensitive configuration values are rendered.

## Frontend Composition Strategy

The Admin Portal is organized as a composition of reusable workspaces rather than independent applications.

Each workspace is built from:

- page entry;
- reusable workspace component;
- dedicated runtime API client;
- normalized backend contract;
- shared layout and navigation.

This approach keeps presentation independent from backend implementation while enabling consistent user experience across the product.

## State Management

Frontend state should remain local whenever possible.

Workspace state is derived from runtime responses instead of duplicating backend lifecycle state.

Persistent business state belongs to PostgreSQL and is exposed through runtime endpoints.

## Scalability Guidelines

As the platform grows:

- new product capabilities should extend existing workspaces before introducing new navigation areas;
- reusable UI components should be preferred over duplicated implementations;
- runtime contracts should remain stable and versioned;
- frontend performance should prioritize lazy loading, incremental rendering and bounded datasets.

## Production Principles

The frontend must remain free of business orchestration, customer-specific assumptions and mock production data.

Every production workspace should consume runtime endpoints and clearly expose readiness, diagnostics, warnings and pending capabilities to operators.