# SHEKU Installation

Supported installation, first-run bootstrap and startup guidance for the SHEKU 1.6.0 release line.

For a new single-host installation, use the product installer rather than development-only supervisors or manual database/bootstrap steps.

## Canonical installation documents

1. [System Requirements](system-requirements.md) — supported operating systems, architectures, host software, Docker access, ports and persistent-storage requirements.
2. [Installation Guide](installation-guide.md) — clean installation, preflight, first-run setup, verification and common failures.
3. [Local Runtime Operations](local-runtime.md) — development and operational runtime controls.
4. [Production Readiness](../deployment/PRODUCTION_READINESS.md) — additional controls required for production deployment.

The supported first-install path is:

```text
git clone
→ checkout release branch
→ ./scripts/install-platform.sh
→ /setup
→ Organization
→ Administrator
→ Preferences
→ Completion Evidence
→ Login
```

SHEKU may be deployed locally, on-premise, hybrid or cloud-based, but every supported topology must preserve the same persistence, organization-isolation, idempotency and optional-AI invariants.
