# Admin Portal Validation

## Purpose

This validation checks that the administrative portal is reachable on the fixed local endpoint and remains aligned with the platform API configuration.

It is a lightweight deployment validation. It does not replace browser-level interaction tests for complex client behavior.

## Command

From the repository root:

```powershell
python scripts/validate_admin_portal.py
```

## Fixed endpoints

```text
API:    http://127.0.0.1:8000
Portal: http://127.0.0.1:3000
```

## Routes validated

```text
/
/operations
/organization
/documents
/knowledge
/connectors
/runtime
/scheduler
/ai
```

For every route, the validation checks:

- HTTP 200;
- rendered HTML document;
- platform title presence;
- Next.js payload or asset presence;
- non-empty response body;
- response duration.

## API alignment

The validation also checks:

- `/health/ready` reports ready;
- `/platform/configuration` reports portal port `3000`;
- effective CORS configuration includes the local portal origin;
- `/platform/status` is available.

## Evidence

Results are written to:

```text
runtime/evidence/admin-portal-validation.json
```

A successful execution includes:

```json
{
  "status": "passed",
  "steps": [
    "platform_started",
    "all_routes_rendered",
    "api_configuration_verified",
    "platform_metadata_verified",
    "clean_shutdown"
  ]
}
```

## Scope boundary

This validation confirms portal deployment, route rendering and API configuration coherence. Browser interaction, accessibility, visual regression and form workflows should be added later as dedicated UI test suites when the portal stabilizes.

## Governed security contracts

Run from `apps/admin-portal`:

```bash
../../node_modules/.bin/tsc --noEmit --pretty false -p tsconfig.json
node scripts/validate-i18n.mjs
node scripts/check-global-user-management-contract.mjs
node scripts/check-global-user-editor-state.mjs
node scripts/check-global-role-management-contract.mjs
node scripts/check-session-lifecycle-contract.mjs
```

These scripts validate contracts and reducer transitions; they do not replace an authenticated browser smoke. The August 2026 pre-production smoke verified both managed identities in read and edit modes, cancellation, identity switching, mutually exclusive creation/editing and disabled save without changes.

Browser automation may redact DOM values for fields classified as `username` or `email`. Visual inspection is required before treating an empty automation value as an application defect.
