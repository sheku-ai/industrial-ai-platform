create table knowledge_sources (
 id uuid primary key,
 document_id uuid not null,
 source_type text not null,
 status text not null default 'active'
);

create table chunks (
 id uuid primary key,
 source_id uuid not null,
 chunk_index integer not null,
 content text not null,
 metadata jsonb not null default '{}'
);

create table embeddings (
 id uuid primary key,
 chunk_id uuid not null,
 model_name text not null,
 vector_id text not null,
 created_at timestamptz not null default now()
);

create table search_queries (
 id uuid primary key,
 query_text text not null,
 created_at timestamptz not null default now()
);

create table citations (
 id uuid primary key,
 query_id uuid not null,
 chunk_id uuid not null,
 score numeric
);
