-- Superchat 0001: core tables
-- Safe to re-run.

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

-- Normalised key used to match company / product names ("Acme  Corp" = "acme corp")
create or replace function public.name_key(t text)
returns text language sql immutable as $$
  select lower(regexp_replace(btrim(coalesce(t, '')), '\s+', ' ', 'g'))
$$;

-- People ------------------------------------------------------------------
create table if not exists public.members (
  user_id      uuid primary key references auth.users (id) on delete cascade,
  email        text not null,
  display_name text,
  created_at   timestamptz not null default now()
);

-- Edited by the project owner in the Supabase dashboard. Never readable from the app.
create table if not exists public.admin_emails (
  email text primary key check (email = lower(email))
);

-- Companies and products -----------------------------------------------------
create table if not exists public.companies (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (btrim(name) <> ''),
  name_key   text not null unique,
  aliases    text[] not null default '{}',
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  hidden_at  timestamptz
);

create table if not exists public.products (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies (id) on delete cascade,
  name       text not null check (btrim(name) <> ''),
  name_key   text not null,
  aliases    text[] not null default '{}',
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  hidden_at  timestamptz,
  unique (company_id, name_key)
);

-- Shared "this project folder belongs to this company/product" memory
create table if not exists public.folder_links (
  folder_key text primary key,
  company_id uuid not null references public.companies (id) on delete cascade,
  product_id uuid references public.products (id) on delete set null,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now()
);

-- Decisions --------------------------------------------------------------------
create table if not exists public.decisions (
  id              uuid primary key default gen_random_uuid(),
  keep_id         uuid not null unique,            -- client-generated; makes push retry-safe
  chat_id         text,
  kind            text not null default 'decision' check (kind in ('decision', 'key_note')),
  title           text not null check (btrim(title) <> ''),
  decision        text not null check (btrim(decision) <> ''),
  condition       text,                            -- when this applies
  reason          text,
  original_text   text,                            -- the person's own wording
  company_id      uuid references public.companies (id),
  product_id      uuid references public.products (id),
  status          text not null default 'unsaved' check (status in ('unsaved', 'saved')),
  author_id       uuid not null default auth.uid() references auth.users (id),
  source_agent    text,
  folder_key      text,
  kept_at         timestamptz not null default now(),
  pushed_at       timestamptz,
  hidden_at       timestamptz,
  hidden_by       uuid references auth.users (id) on delete set null,
  embedding       extensions.vector(384),
  embedding_model text,
  fts             tsvector generated always as (
    to_tsvector('english'::regconfig,
      coalesce(title, '') || ' ' || coalesce(decision, '') || ' ' || coalesce(condition, '') || ' ' ||
      coalesce(reason, '') || ' ' || coalesce(original_text, ''))
  ) stored,
  constraint saved_needs_company   check (status <> 'saved' or company_id is not null),
  constraint product_needs_company check (product_id is null or company_id is not null)
);

create index if not exists decisions_fts_idx      on public.decisions using gin (fts);
create index if not exists decisions_embedding_idx on public.decisions using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists decisions_company_idx  on public.decisions (company_id, product_id) where status = 'saved';
create index if not exists decisions_chat_idx     on public.decisions (chat_id);
create index if not exists decisions_author_idx   on public.decisions (author_id, status);

create table if not exists public.decision_conflicts (
  id          uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.decisions (id) on delete cascade,
  other_id    uuid not null references public.decisions (id) on delete cascade,
  note        text,
  created_by  uuid references auth.users (id) on delete set null,
  created_at  timestamptz not null default now(),
  check (decision_id <> other_id),
  unique (decision_id, other_id)
);

create table if not exists public.decision_history (
  id          bigserial primary key,
  decision_id uuid not null,
  action      text not null,
  old_row     jsonb,
  new_row     jsonb,
  actor       uuid,
  at          timestamptz not null default now()
);
create index if not exists decision_history_decision_idx on public.decision_history (decision_id, at);

-- One row per push: this device's "last pushed" cut-off
create table if not exists public.push_batches (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  device_id  text not null,
  cutoff_at  timestamptz not null,
  item_count int not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists push_batches_idx on public.push_batches (user_id, device_id, cutoff_at desc);
