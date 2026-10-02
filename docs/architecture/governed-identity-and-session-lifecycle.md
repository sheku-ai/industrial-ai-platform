# Governed Identity and Session Lifecycle

## Purpose

This document defines the authoritative local-identity, platform-access and authentication-session architecture introduced by the August 2026 security stabilization.

## Data authorities

```text
Identity PostgreSQL
  users
  organization_memberships
  auth_sessions
  session_policies
  authentication_events

Platform PostgreSQL
  roles
  permissions
  role_assignments
  policies
  audit_events
```

Identity and Platform PostgreSQL have independent Alembic chains. Their current repository heads are `20260811_1030` and `20260807_995`, respectively.

## Session policy

Exactly one active platform policy governs:

- standard idle timeout;
- standard absolute timeout;
- maximum concurrent sessions;
- activity write interval;
- Remember me enablement;
- Remember me idle and absolute timeouts;
- historical retention.

Policy changes are versioned. New sessions always use the active policy. Restrictive application may shorten existing sessions but must never extend their expiry.

## Session creation and validation

```text
identity lock
-> credential validation
-> active policy read
-> session expiry calculation in UTC
-> opaque token persistence
-> deterministic concurrent-limit enforcement
-> secure cookie + CSRF contract
```

A session is effective only when it is not revoked and both idle and absolute expirations remain in the future. Activity writes are limited by the configured interval.

Standard login cookies remain browser-session cookies. Remember me is available only when the active policy permits it.

## Revocation

Logout, password change, administrative password reset and identity deactivation call the centralized revocation service. Revocation records actor, operation, reason and safe metadata. Tokens, hashes, cookie values and secrets are never returned or audited.

Identity locking serializes login, reset and deactivation for the same user to prevent races.

## Platform security administration

Administrative endpoints require persisted effective permission `platform.security:administer`. The administration surface supports:

- session policy read/update;
- global user lifecycle and profile management;
- global platform-role catalogue and assignment;
- organization memberships and organization roles;
- user session listing and revocation.

The final active global administrator is protected from deactivation or authority removal.

## Client evidence

The immediate network peer is parsed as IPv4 or IPv6. Forwarded headers are considered only when that peer belongs to `AUTH_TRUSTED_PROXY_NETWORKS`. The resolver validates the complete chain and selects the first untrusted hop when walking from the server side. Malformed or untrusted input falls back to the direct peer.

IP and device evidence are approximate audit metadata and never authorize access.

## Portal state boundary

The global profile editor separates authoritative view state from an explicit edit draft. Identity selection replaces the complete state. Partial or stale responses cannot overwrite a complete authoritative identity. Creation and editing are mutually exclusive, and save is disabled without valid changes.

Browser automation systems may redact values for inputs marked as username or email. Visual verification is required before classifying those redacted values as an application defect.
