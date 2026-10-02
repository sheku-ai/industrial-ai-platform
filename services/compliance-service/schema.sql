create table compliance_frameworks (
  id uuid primary key,
  name text not null,
  version text,
  status text not null default 'active'
);

create table controls (
  id uuid primary key,
  framework_id uuid references compliance_frameworks(id),
  code text not null,
  title text not null,
  description text,
  owner text,
  status text not null default 'draft'
);

create table evidence (
  id uuid primary key,
  title text not null,
  evidence_type text,
  owner text,
  source text,
  created_at timestamptz default now()
);

create table control_evidence (
  control_id uuid references controls(id),
  evidence_id uuid references evidence(id)
);

create table findings (
  id uuid primary key,
  control_id uuid references controls(id),
  severity text,
  description text,
  status text default 'open'
);

create table corrective_actions (
  id uuid primary key,
  finding_id uuid references findings(id),
  owner text,
  due_date date,
  status text default 'open'
);

create table audit_events (
  id uuid primary key,
  actor text,
  event_type text,
  target_object text,
  payload jsonb default '{}',
  created_at timestamptz default now()
);