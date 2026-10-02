create table companies (
  id uuid primary key,
  name text not null,
  code text unique,
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table organization_units (
  id uuid primary key,
  company_id uuid not null references companies(id),
  parent_id uuid references organization_units(id),
  type text not null,
  name text not null,
  code text,
  status text not null default 'active',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table relationships (
  id uuid primary key,
  source_id uuid not null references organization_units(id),
  target_id uuid not null references organization_units(id),
  relation_type text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table roles (
  id uuid primary key,
  company_id uuid not null references companies(id),
  name text not null,
  scope text not null,
  permissions jsonb not null default '[]',
  created_at timestamptz not null default now()
);
