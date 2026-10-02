create table document_types (
  id uuid primary key,
  company_id uuid not null,
  name text not null,
  code text not null,
  description text,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique(company_id, code)
);

create table metadata_schemas (
  id uuid primary key,
  document_type_id uuid not null references document_types(id),
  version integer not null default 1,
  name text not null,
  status text not null default 'draft',
  created_at timestamptz not null default now()
);

create table metadata_fields (
  id uuid primary key,
  schema_id uuid not null references metadata_schemas(id),
  name text not null,
  label text not null,
  field_type text not null,
  required boolean not null default false,
  options jsonb not null default '[]',
  validation jsonb not null default '{}',
  display_order integer not null default 0
);

create table document_collections (
  id uuid primary key,
  company_id uuid not null,
  name text not null,
  scope jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table documents (
  id uuid primary key,
  company_id uuid not null,
  collection_id uuid references document_collections(id),
  document_type_id uuid references document_types(id),
  title text not null,
  source_uri text,
  classification text not null default 'internal',
  lifecycle_state text not null default 'draft',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table document_versions (
  id uuid primary key,
  document_id uuid not null references documents(id),
  version_label text not null,
  storage_uri text not null,
  checksum text,
  created_at timestamptz not null default now()
);

create table tags (
  id uuid primary key,
  company_id uuid not null,
  name text not null,
  created_at timestamptz not null default now()
);

create table document_tags (
  document_id uuid not null references documents(id),
  tag_id uuid not null references tags(id),
  primary key(document_id, tag_id)
);
