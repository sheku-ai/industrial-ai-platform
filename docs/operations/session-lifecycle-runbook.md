# Session Lifecycle Runbook

## Scope

Operational procedure for governed local sessions in a persistent pre-production or production-like deployment.

## Backup before migration

Create a custom-format backup from the Identity PostgreSQL container and store it outside the container. Validate it with the matching PostgreSQL major-version tools:

```bash
docker exec -i industrial-ai-clean-identity-postgres-1 \
  pg_restore --list \
  < runtime/backups/identity-before-session-lifecycle.dump \
  > /tmp/identity-backup-contents.txt
```

A non-empty file alone is not sufficient evidence; `pg_restore --list` must return zero.

## Apply the independent identity migration

```bash
docker compose -p industrial-ai-clean -f docker-compose.yml \
  run --rm identity-migrator
```

Expected Identity revision:

```text
20260811_1030
```

Verify:

- `identity.session_policies` exists as a table;
- exactly one active platform policy exists;
- all lifecycle columns in `identity.auth_sessions` are backfilled;
- no session has null lifecycle fields.

## Rebuild and health

```bash
docker compose -p industrial-ai-clean -f docker-compose.yml build api portal
docker compose -p industrial-ai-clean -f docker-compose.yml up -d --no-deps api portal
docker compose -p industrial-ai-clean -f docker-compose.yml ps api portal
curl -sS http://127.0.0.1:8000/health/ready | python -m json.tool
```

Both Platform and Identity PostgreSQL must report healthy.

## Trusted proxy configuration

Resolve the exact immediate proxy address attached to the API network and configure a host CIDR:

```bash
export AUTH_TRUSTED_PROXY_NETWORKS='192.0.2.10/32'
export AUTH_FORWARDED_IP_HEADERS='forwarded,x-forwarded-for'
docker compose -p industrial-ai-clean -f docker-compose.yml \
  up -d --no-deps --force-recreate api
```

The address above is an example, not a product default. Re-resolve it for the actual deployment. Do not use `$172...`; that syntax expands a shell variable and corrupts the value.

## Retention and controlled revocation

Preview is the default:

```bash
docker compose exec api python -m app.cli revoke-auth-sessions \
  --user-id <IDENTITY_UUID> \
  --actor-reference <AUDITED_ACTOR_REFERENCE>
```

Execute only after reviewing the preview:

```bash
docker compose exec api python -m app.cli revoke-auth-sessions \
  --user-id <IDENTITY_UUID> \
  --actor-reference <AUDITED_ACTOR_REFERENCE> \
  --execute
```

## Portal validation

Use an authenticated session and verify:

1. session policy loads;
2. self-service sessions paginate and filter;
3. current session is identifiable;
4. terminal sessions cannot be revoked again;
5. global user sessions require the administrative permission;
6. profile view/edit/cancel works for more than one identity;
7. creation and editing are not mounted simultaneously;
8. no persistent values are changed during a read-only smoke.
