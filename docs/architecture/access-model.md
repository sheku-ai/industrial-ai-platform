# Access Model

The platform uses persisted roles, permissions and assignments. UI visibility never replaces backend authorization.

## Authorities

- Identity PostgreSQL: users, usernames, credential state, organization memberships, authentication sessions, session policy and identity audit.
- Platform PostgreSQL: roles, permissions, role assignments, access policies and product-domain authorization evidence.

## Effective access flow

```text
Authenticated identity
-> persisted role assignment
-> active role in platform or organization scope
-> persisted permission
-> backend authorization gate
-> audited operation
```

A platform role is catalogued when `organization_id IS NULL` and `config.scope = platform`. Effective authorization additionally requires an active role and active assignment. The legacy `is_system` flag does not define platform scope.

## Security administration

Global identity, role and session administration requires:

```text
platform.security:administer
```

The backend enforces this permission for every administrative route. The portal uses the resolved capability only to present or hide controls.

Non-configurable platform roles remain visible for consistency but their mutation is blocked. Assigned roles that are no longer available are returned explicitly as inconsistencies instead of being silently discarded.

## Organization access

Organization access requires an active Identity PostgreSQL membership plus the applicable organization-scoped role assignment in Platform PostgreSQL. Client-supplied organization identifiers do not create authority.

## Session boundary

Possession of a valid opaque session is necessary but not sufficient. Each request also applies expiration, revocation, CSRF and effective-permission checks. Client IP and device labels are audit evidence only.

## Safety invariants

- The final active global administrator cannot be deactivated or stripped of required authority.
- Password change/reset and identity deactivation use centralized session revocation.
- Authorization is evaluated from persisted state.
- Tokens, hashes, cookies and secrets are never returned by management APIs.
