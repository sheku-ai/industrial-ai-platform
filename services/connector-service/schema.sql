create table connectors (
  id uuid primary key,
  name text not null,
  code text unique not null,
  version text not null,
  connector_type text not null,
  status text not null default 'active',
  configuration_schema jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table connector_instances (
  id uuid primary key,
  connector_id uuid not null references connectors(id),
  tenant_id uuid,
  name text not null,
  configuration jsonb not null default '{}',
  status text not null default 'enabled',
  created_at timestamptz not null default now()
);

create table connector_sync_jobs (
  id uuid primary key,
  connector_instance_id uuid not null references connector_instances(id),
  status text not null default 'pending',
  sync_type text not null default 'full',
  started_at timestamptz,
  finished_at timestamptz,
  statistics jsonb not null default '{}',
  error_message text
);

create table connector_events (
  id uuid primary key,
  connector_instance_id uuid references connector_instances(id),
  event_type text not null,
  message text,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now()
);
