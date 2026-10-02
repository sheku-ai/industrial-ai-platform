create table users (
 id uuid primary key,
 email text unique not null,
 display_name text not null,
 status text not null default 'active'
);

create table groups (
 id uuid primary key,
 name text not null,
 description text
);

create table permissions (
 id uuid primary key,
 code text unique not null,
 description text
);

create table role_permissions (
 role_id uuid not null,
 permission_id uuid not null,
 primary key(role_id, permission_id)
);

create table role_assignments (
 id uuid primary key,
 user_id uuid not null,
 role_id uuid not null,
 scope_type text not null,
 scope_id uuid not null
);

create table access_policies (
 id uuid primary key,
 name text not null,
 resource_type text not null,
 rules jsonb not null default '{}'
);
