create table marketplace_packages (
 id uuid primary key,
 name text not null,
 code text unique not null,
 vendor text,
 package_type text not null,
 latest_version text not null,
 description text,
 created_at timestamptz not null default now()
);

create table package_versions (
 id uuid primary key,
 package_id uuid not null references marketplace_packages(id),
 version text not null,
 manifest jsonb not null default '{}',
 published_at timestamptz not null default now()
);

create table installed_packages (
 id uuid primary key,
 package_id uuid not null references marketplace_packages(id),
 version text not null,
 status text not null default 'installed',
 installed_at timestamptz not null default now()
);

create table package_dependencies (
 id uuid primary key,
 package_id uuid not null references marketplace_packages(id),
 dependency_code text not null,
 dependency_version text
);
