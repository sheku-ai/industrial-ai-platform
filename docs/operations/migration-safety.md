# Migration Safety

## Purpose

Database migrations are forward-only and guarded. The platform must not start against an unknown, divergent or pending schema.

## Supported commands

From `apps/api`:

```powershell
python migration_guard.py check
python migration_guard.py apply
```

`check` reports repository heads, database heads, pending revisions and startup compatibility.

`apply`:

1. validates repository and database state;
2. refuses ambiguous or divergent states;
3. runs only `upgrade head`;
4. measures migration duration;
5. validates the final database revision;
6. exits non-zero unless the final state is startup-compatible.

## Compatibility states

```text
compatible
pending
unversioned
multiple_repository_heads
multiple_database_heads
unknown_database_revision
database_ahead_or_diverged
```

Only `compatible` permits API startup.

`pending` and `unversioned` may be advanced by the guarded migrator.

The following states block migration and startup:

- multiple repository heads;
- multiple database heads;
- unknown database revision;
- database ahead of or divergent from the repository chain.

## Compose policy

The Compose migrator executes:

```text
python migration_guard.py apply
```

API and scheduler services depend on successful migrator completion.

## API startup policy

The API independently validates schema compatibility during startup.

This provides defense in depth for manual startup and non-Compose execution. A process cannot begin serving traffic if its database revision does not exactly match the repository head.

## Destructive behavior

The migration guard never invokes:

```text
downgrade
stamp
```

Destructive migration behavior is not automatic. Any future migration containing destructive DDL requires explicit architecture review, backup strategy and release evidence.

## Evidence

Successful application prints JSON containing:

- compatibility;
- repository heads;
- database heads;
- pending revisions;
- startup compatibility;
- migration requirement;
- execution duration.

## Independent Identity PostgreSQL migrations

Identity PostgreSQL uses `apps/api/identity_alembic.ini` and must be evaluated independently from Platform PostgreSQL. Current repository heads are:

```text
Platform PostgreSQL: 20260807_995
Identity PostgreSQL: 20260811_1030
```

The governed-session migration backfills existing sessions and adds non-null lifecycle fields and coherent PostgreSQL constraints. Before applying it to a persistent environment:

1. create a custom-format Identity PostgreSQL backup;
2. validate the archive with `pg_restore --list` using a PostgreSQL 16 client;
3. record the current Identity revision;
4. run the identity migrator;
5. verify the new revision, active policy row and incomplete-backfill count;
6. recreate API and Portal only after the migration succeeds.

Never edit a published migration. Follow-up schema corrections require a new revision.
