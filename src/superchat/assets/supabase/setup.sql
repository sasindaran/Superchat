-- ================================================================
-- Superchat: complete database setup for Supabase.
-- Paste this whole file into Supabase > SQL Editor > New query > Run.
-- Safe to run more than once.
-- GENERATED from supabase/migrations/*.sql by build_setup.py. Do not edit by hand.
-- ================================================================

-- ---------- 0001_core.sql ----------
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

-- ---------- 0002_security.sql ----------
-- Superchat 0002: row level security
-- Safe to re-run.

-- Who is asking? -------------------------------------------------------------
create or replace function public.is_member()
returns boolean language sql stable security definer set search_path = public as $$
  select auth.uid() is not null
     and exists (select 1 from public.members m where m.user_id = auth.uid())
$$;

create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select auth.uid() is not null
     and exists (
       select 1 from public.admin_emails a
       where a.email = lower(coalesce(auth.jwt() ->> 'email', ''))
     )
$$;

-- Turn everything on, then grant narrowly ------------------------------------
alter table public.members            enable row level security;
alter table public.admin_emails       enable row level security;
alter table public.companies          enable row level security;
alter table public.products           enable row level security;
alter table public.folder_links       enable row level security;
alter table public.decisions          enable row level security;
alter table public.decision_conflicts enable row level security;
alter table public.decision_history   enable row level security;
alter table public.push_batches       enable row level security;

revoke all on public.members, public.admin_emails, public.companies, public.products,
              public.folder_links, public.decisions, public.decision_conflicts,
              public.decision_history, public.push_batches
  from anon, authenticated, public;

grant usage on schema public to anon, authenticated;
grant select                         on public.members            to authenticated;
grant select, insert                 on public.companies          to authenticated;
grant select, insert                 on public.products           to authenticated;
grant select, insert, update, delete on public.folder_links       to authenticated;
grant select, insert, delete         on public.decisions          to authenticated;
grant select, insert                 on public.decision_conflicts to authenticated;
grant select                         on public.decision_history   to authenticated;
grant select, insert                 on public.push_batches       to authenticated;
-- admin_emails: no grant at all. Only the SECURITY DEFINER is_admin() reads it.

-- Column-level: people may edit the words, never status / author / visibility / ids.
grant update (title, decision, condition, reason, original_text, kind,
              company_id, product_id, embedding, embedding_model)
  on public.decisions to authenticated;
grant update (name, aliases, hidden_at) on public.companies to authenticated;
grant update (name, aliases, hidden_at) on public.products  to authenticated;
grant delete on public.companies, public.products, public.decision_conflicts to authenticated;

-- members -------------------------------------------------------------------
drop policy if exists members_read on public.members;
create policy members_read on public.members for select to authenticated
  using (public.is_member());

-- companies / products ------------------------------------------------------
drop policy if exists companies_read on public.companies;
create policy companies_read on public.companies for select to authenticated
  using (public.is_member() and (hidden_at is null or public.is_admin()));
drop policy if exists companies_add on public.companies;
create policy companies_add on public.companies for insert to authenticated
  with check (public.is_member() and created_by = auth.uid());
drop policy if exists companies_admin_edit on public.companies;
create policy companies_admin_edit on public.companies for update to authenticated
  using (public.is_admin()) with check (public.is_admin());
drop policy if exists companies_admin_delete on public.companies;
create policy companies_admin_delete on public.companies for delete to authenticated
  using (public.is_admin());

drop policy if exists products_read on public.products;
create policy products_read on public.products for select to authenticated
  using (public.is_member() and (hidden_at is null or public.is_admin()));
drop policy if exists products_add on public.products;
create policy products_add on public.products for insert to authenticated
  with check (public.is_member() and created_by = auth.uid());
drop policy if exists products_admin_edit on public.products;
create policy products_admin_edit on public.products for update to authenticated
  using (public.is_admin()) with check (public.is_admin());
drop policy if exists products_admin_delete on public.products;
create policy products_admin_delete on public.products for delete to authenticated
  using (public.is_admin());

-- folder_links --------------------------------------------------------------
drop policy if exists folder_links_read on public.folder_links;
create policy folder_links_read on public.folder_links for select to authenticated
  using (public.is_member());
drop policy if exists folder_links_add on public.folder_links;
create policy folder_links_add on public.folder_links for insert to authenticated
  with check (public.is_member() and created_by = auth.uid());
drop policy if exists folder_links_edit on public.folder_links;
create policy folder_links_edit on public.folder_links for update to authenticated
  using (public.is_member() and (created_by = auth.uid() or public.is_admin()))
  with check (public.is_member() and (created_by = auth.uid() or public.is_admin()));
drop policy if exists folder_links_delete on public.folder_links;
create policy folder_links_delete on public.folder_links for delete to authenticated
  using (public.is_member() and (created_by = auth.uid() or public.is_admin()));

-- decisions -----------------------------------------------------------------
-- Saved:   every member reads (hidden ones: admin and the author only).
-- Unsaved: the author only. Not even admins.
drop policy if exists decisions_read on public.decisions;
create policy decisions_read on public.decisions for select to authenticated
  using (
    public.is_member() and (
      (status = 'saved' and (hidden_at is null or author_id = auth.uid() or public.is_admin()))
      or (status = 'unsaved' and author_id = auth.uid())
    )
  );

-- Directly, a member can only create their own unsaved draft.
-- Saved decisions only come into existence through push_review().
drop policy if exists decisions_add_draft on public.decisions;
create policy decisions_add_draft on public.decisions for insert to authenticated
  with check (
    public.is_member() and author_id = auth.uid() and status = 'unsaved'
    and hidden_at is null and pushed_at is null
  );

drop policy if exists decisions_edit on public.decisions;
create policy decisions_edit on public.decisions for update to authenticated
  using (public.is_member() and hidden_at is null and (author_id = auth.uid() or (status = 'saved' and public.is_admin())))
  with check (public.is_member() and (author_id = auth.uid() or public.is_admin()));

-- Drafts can be thrown away by their author. Saved decisions are never deleted, only hidden.
drop policy if exists decisions_delete_draft on public.decisions;
create policy decisions_delete_draft on public.decisions for delete to authenticated
  using (public.is_member() and status = 'unsaved' and author_id = auth.uid());

-- conflicts -----------------------------------------------------------------
drop policy if exists conflicts_read on public.decision_conflicts;
create policy conflicts_read on public.decision_conflicts for select to authenticated
  using (public.is_member());
drop policy if exists conflicts_add on public.decision_conflicts;
create policy conflicts_add on public.decision_conflicts for insert to authenticated
  with check (public.is_member() and created_by = auth.uid());
drop policy if exists conflicts_admin_delete on public.decision_conflicts;
create policy conflicts_admin_delete on public.decision_conflicts for delete to authenticated
  using (public.is_admin());

-- history: admins read, a trigger writes ------------------------------------
drop policy if exists history_admin_read on public.decision_history;
create policy history_admin_read on public.decision_history for select to authenticated
  using (public.is_admin());

-- push_batches: your own only -------------------------------------------------
drop policy if exists batches_read on public.push_batches;
create policy batches_read on public.push_batches for select to authenticated
  using (user_id = auth.uid());
drop policy if exists batches_add on public.push_batches;
create policy batches_add on public.push_batches for insert to authenticated
  with check (user_id = auth.uid() and public.is_member());

-- ---------- 0003_functions.sql ----------
-- Superchat 0003: functions
-- Safe to re-run.

create or replace function public.superchat_version()
returns text language sql immutable as $$ select '1'::text $$;

-- Internal helpers (not callable by app users) --------------------------------
create or replace function public._resolve_company(spec jsonb, uid uuid)
returns uuid language plpgsql set search_path = public, extensions as $$
declare
  v_id uuid; v_name text; v_hidden timestamptz;
begin
  if spec is null or jsonb_typeof(spec) <> 'object' then
    raise exception 'company is required';
  end if;

  if nullif(spec ->> 'id', '') is not null then
    select id, hidden_at into v_id, v_hidden from public.companies where id = (spec ->> 'id')::uuid;
    if v_id is null then raise exception 'company % not found', spec ->> 'id'; end if;
    if v_hidden is not null then raise exception 'company is hidden; ask an admin to restore it'; end if;
    return v_id;
  end if;

  v_name := btrim(coalesce(spec ->> 'name', ''));
  if v_name = '' then raise exception 'company is required'; end if;

  select id, hidden_at into v_id, v_hidden from public.companies where name_key = public.name_key(v_name);
  if v_id is null then
    select c.id, c.hidden_at into v_id, v_hidden from public.companies c
    where exists (select 1 from unnest(c.aliases) a where public.name_key(a) = public.name_key(v_name))
    limit 1;
  end if;
  if v_id is not null then
    if v_hidden is not null then raise exception 'company "%" is hidden; ask an admin to restore it', v_name; end if;
    return v_id;
  end if;

  insert into public.companies (name, name_key, created_by)
  values (v_name, public.name_key(v_name), uid) returning id into v_id;
  return v_id;
end $$;

create or replace function public._resolve_product(p_company uuid, spec jsonb, uid uuid)
returns uuid language plpgsql set search_path = public, extensions as $$
declare
  v_id uuid; v_name text; v_hidden timestamptz; v_co uuid;
begin
  if spec is null or jsonb_typeof(spec) <> 'object' then return null; end if;

  if nullif(spec ->> 'id', '') is not null then
    select id, company_id, hidden_at into v_id, v_co, v_hidden from public.products where id = (spec ->> 'id')::uuid;
    if v_id is null then raise exception 'product % not found', spec ->> 'id'; end if;
    if v_co <> p_company then raise exception 'product does not belong to that company'; end if;
    if v_hidden is not null then raise exception 'product is hidden; ask an admin to restore it'; end if;
    return v_id;
  end if;

  v_name := btrim(coalesce(spec ->> 'name', ''));
  if v_name = '' then return null; end if;   -- empty product = company-wide

  select id, hidden_at into v_id, v_hidden from public.products
   where company_id = p_company and name_key = public.name_key(v_name);
  if v_id is null then
    select p.id, p.hidden_at into v_id, v_hidden from public.products p
    where p.company_id = p_company
      and exists (select 1 from unnest(p.aliases) a where public.name_key(a) = public.name_key(v_name))
    limit 1;
  end if;
  if v_id is not null then
    if v_hidden is not null then raise exception 'product "%" is hidden; ask an admin to restore it', v_name; end if;
    return v_id;
  end if;

  insert into public.products (company_id, name, name_key, created_by)
  values (p_company, v_name, public.name_key(v_name), uid) returning id into v_id;
  return v_id;
end $$;

-- push_review: the one way a decision becomes "saved" ---------------------------
-- p_items: [{keep_id, chat_id, kind, title, decision, condition, reason, original_text,
--            source_agent, folder_key, kept_at, company:{id|name}, product:{id|name}|null,
--            embedding:[384 numbers]|null, embedding_model, conflicts:[{other_id, note}]}]
-- Runs as ONE transaction: any error undoes everything, including new companies.
-- Safe to retry: a keep_id that is already saved is skipped.
create or replace function public.push_review(
  p_device_id        text,
  p_cutoff           timestamptz,
  p_items            jsonb,
  p_remove_keep_ids  uuid[] default '{}'
) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  uid uuid := auth.uid();
  it jsonb; c jsonb;
  v_keep uuid; v_company uuid; v_product uuid; v_dec uuid; v_other uuid;
  v_ex record; v_emb extensions.vector;
  v_saved int := 0; v_skipped int := 0; v_removed int := 0; v_conflicts int := 0;
  v_ids jsonb := '[]'::jsonb;
begin
  if uid is null or not public.is_member() then
    raise exception 'not a member' using errcode = '42501';
  end if;
  if p_items is null or jsonb_typeof(p_items) <> 'array' then raise exception 'items must be a JSON array'; end if;
  if coalesce(btrim(p_device_id), '') = '' then raise exception 'device_id is required'; end if;
  if p_cutoff is null then raise exception 'cutoff is required'; end if;

  for it in select value from jsonb_array_elements(p_items) loop
    v_keep := nullif(it ->> 'keep_id', '')::uuid;
    if v_keep is null then raise exception 'every item needs a keep_id'; end if;

    select * into v_ex from public.decisions where keep_id = v_keep;
    if found and v_ex.status = 'saved' then
      v_skipped := v_skipped + 1;
      v_ids := v_ids || jsonb_build_object('keep_id', v_keep, 'id', v_ex.id, 'skipped', true);
      continue;
    end if;
    if found and v_ex.author_id <> uid then raise exception 'keep_id % belongs to someone else', v_keep; end if;

    v_company := public._resolve_company(it -> 'company', uid);
    v_product := public._resolve_product(v_company, it -> 'product', uid);
    v_emb := case when jsonb_typeof(it -> 'embedding') = 'array' then (it ->> 'embedding')::extensions.vector else null end;

    if found then
      update public.decisions set
        chat_id = it ->> 'chat_id',
        kind = coalesce(nullif(it ->> 'kind', ''), 'decision'),
        title = it ->> 'title', decision = it ->> 'decision',
        condition = it ->> 'condition', reason = it ->> 'reason', original_text = it ->> 'original_text',
        source_agent = it ->> 'source_agent', folder_key = it ->> 'folder_key',
        company_id = v_company, product_id = v_product,
        embedding = v_emb, embedding_model = it ->> 'embedding_model',
        status = 'saved', pushed_at = now()
      where id = v_ex.id
      returning id into v_dec;
    else
      insert into public.decisions (
        keep_id, chat_id, kind, title, decision, condition, reason, original_text,
        company_id, product_id, status, author_id, source_agent, folder_key,
        kept_at, pushed_at, embedding, embedding_model)
      values (
        v_keep, it ->> 'chat_id', coalesce(nullif(it ->> 'kind', ''), 'decision'),
        it ->> 'title', it ->> 'decision', it ->> 'condition', it ->> 'reason', it ->> 'original_text',
        v_company, v_product, 'saved', uid, it ->> 'source_agent', it ->> 'folder_key',
        coalesce(nullif(it ->> 'kept_at', '')::timestamptz, now()), now(), v_emb, it ->> 'embedding_model')
      returning id into v_dec;
    end if;
    v_saved := v_saved + 1;
    v_ids := v_ids || jsonb_build_object('keep_id', v_keep, 'id', v_dec, 'company_id', v_company, 'product_id', v_product);

    -- conflicts: shown, never blocking
    for c in select value from jsonb_array_elements(coalesce(it -> 'conflicts', '[]'::jsonb)) loop
      v_other := nullif(c ->> 'other_id', '')::uuid;
      if v_other is not null and v_other <> v_dec and exists (
           select 1 from public.decisions o where o.id = v_other and o.status = 'saved' and o.hidden_at is null) then
        insert into public.decision_conflicts (decision_id, other_id, note, created_by)
        values (v_dec, v_other, c ->> 'note', uid) on conflict do nothing;
        v_conflicts := v_conflicts + 1;
      end if;
    end loop;
  end loop;

  -- items the person un-ticked: their own drafts are deleted for good
  delete from public.decisions
   where keep_id = any(coalesce(p_remove_keep_ids, '{}')) and author_id = uid and status = 'unsaved';
  get diagnostics v_removed = row_count;

  insert into public.push_batches (user_id, device_id, cutoff_at, item_count)
  values (uid, btrim(p_device_id), p_cutoff, v_saved);

  return jsonb_build_object('saved', v_saved, 'skipped', v_skipped, 'removed', v_removed,
                            'conflicts', v_conflicts, 'cutoff', p_cutoff, 'items', v_ids);
end $$;

-- Search: keyword + meaning, merged (reciprocal rank fusion) ---------------------
create or replace function public.search_decisions(
  p_query     text,
  p_embedding extensions.vector(384) default null,
  p_company   uuid default null,
  p_product   uuid default null,
  p_all       boolean default false,
  p_limit     int default 10
) returns table (
  id uuid, kind text, title text, decision text, condition text, reason text,
  company_id uuid, company text, product_id uuid, product text, scope text,
  author_email text, author_name text, kept_at timestamptz, pushed_at timestamptz,
  score double precision, keyword_rank int, vector_rank int, similarity double precision
) language plpgsql stable set search_path = public, extensions as $$
#variable_conflict use_column
declare
  -- "any of these words", best match first (a plain AND would find nothing for a natural question)
  q tsquery := coalesce(
    nullif(replace(plainto_tsquery('english', coalesce(p_query, ''))::text, ' & ', ' | '), '')::tsquery,
    ''::tsquery);
begin
  if not public.is_member() then raise exception 'not a member' using errcode = '42501'; end if;
  if not p_all and p_company is null then raise exception 'company is required unless searching all companies'; end if;

  return query
  with base as (
    select d.* from public.decisions d
    join public.companies c on c.id = d.company_id
    where d.status = 'saved' and d.hidden_at is null and c.hidden_at is null
      and (p_all or d.company_id = p_company)
      and (p_all or p_product is null or d.product_id is null or d.product_id = p_product)
  ),
  kw as (
    select s.id, s.rk from (
      select b.id, row_number() over (order by ts_rank(b.fts, q) desc, b.kept_at desc)::int as rk
      from base b where numnode(q) > 0 and b.fts @@ q) s
    where s.rk <= 50
  ),
  vec as (
    select s.id, s.rk, s.sim from (
      select b.id, row_number() over (order by b.embedding <=> p_embedding)::int as rk,
             (1 - (b.embedding <=> p_embedding))::float8 as sim
      from base b where p_embedding is not null and b.embedding is not null) s
    where s.rk <= 50
  ),
  merged as (
    select coalesce(kw.id, vec.id) as id, kw.rk as krk, vec.rk as vrk, vec.sim as sim,
           (coalesce(1.0 / (60 + kw.rk), 0) + coalesce(1.0 / (60 + vec.rk), 0))::float8 as score
    from kw full join vec on vec.id = kw.id
  )
  select d.id, d.kind, d.title, d.decision, d.condition, d.reason,
         d.company_id, c.name, d.product_id, p.name,
         case when d.product_id is null then 'company' else 'product' end,
         m.email, m.display_name, d.kept_at, d.pushed_at,
         mg.score, mg.krk, mg.vrk, mg.sim
  from merged mg
  join base d on d.id = mg.id
  join public.companies c on c.id = d.company_id
  left join public.products p on p.id = d.product_id
  left join public.members m on m.user_id = d.author_id
  order by mg.score desc, d.kept_at desc
  limit greatest(1, least(coalesce(p_limit, 10), 50));
end $$;

-- Nearest saved decisions in a company: candidates for conflict / duplicate checks
create or replace function public.similar_decisions(
  p_embedding extensions.vector(384),
  p_company   uuid,
  p_limit     int default 5,
  p_exclude   uuid[] default '{}'
) returns table (
  id uuid, title text, decision text, kind text, product_id uuid, product text,
  author_email text, kept_at timestamptz, similarity double precision
) language plpgsql stable set search_path = public, extensions as $$
#variable_conflict use_column
begin
  if not public.is_member() then raise exception 'not a member' using errcode = '42501'; end if;
  return query
  select d.id, d.title, d.decision, d.kind, d.product_id, p.name, m.email, d.kept_at,
         (1 - (d.embedding <=> p_embedding))::float8
  from public.decisions d
  left join public.products p on p.id = d.product_id
  left join public.members m on m.user_id = d.author_id
  where d.status = 'saved' and d.hidden_at is null and d.company_id = p_company
    and d.embedding is not null and not (d.id = any(coalesce(p_exclude, '{}')))
  order by d.embedding <=> p_embedding
  limit greatest(1, least(coalesce(p_limit, 5), 25));
end $$;

-- Everything known about a company (and optionally one product) -------------------
create or replace function public.company_brief(p_company uuid, p_product uuid default null)
returns jsonb language plpgsql stable set search_path = public, extensions as $$
declare
  v_company jsonb; v_guidelines jsonb; v_products jsonb; v_conflicts jsonb;
begin
  if not public.is_member() then raise exception 'not a member' using errcode = '42501'; end if;

  select jsonb_build_object('id', c.id, 'name', c.name) into v_company
  from public.companies c where c.id = p_company and c.hidden_at is null;
  if v_company is null then raise exception 'company not found'; end if;

  select coalesce(jsonb_agg(x order by (x ->> 'kept_at') desc), '[]'::jsonb) into v_guidelines from (
    select jsonb_build_object('id', d.id, 'kind', d.kind, 'title', d.title, 'decision', d.decision,
             'condition', d.condition, 'reason', d.reason, 'author', m.email, 'kept_at', d.kept_at) as x
    from public.decisions d left join public.members m on m.user_id = d.author_id
    where d.status = 'saved' and d.hidden_at is null and d.company_id = p_company and d.product_id is null
    order by d.kept_at desc limit 100) g;

  if p_product is null then
    v_products := '[]'::jsonb;
  else
    select coalesce(jsonb_agg(x order by (x ->> 'kept_at') desc), '[]'::jsonb) into v_products from (
      select jsonb_build_object('id', d.id, 'kind', d.kind, 'title', d.title, 'decision', d.decision,
               'condition', d.condition, 'reason', d.reason, 'product', p.name,
               'author', m.email, 'kept_at', d.kept_at) as x
      from public.decisions d
      join public.products p on p.id = d.product_id
      left join public.members m on m.user_id = d.author_id
      where d.status = 'saved' and d.hidden_at is null and d.company_id = p_company and d.product_id = p_product
      order by d.kept_at desc limit 100) g;
  end if;

  select coalesce(jsonb_agg(x), '[]'::jsonb) into v_conflicts from (
    select jsonb_build_object(
             'note', k.note,
             'a', jsonb_build_object('id', a.id, 'title', a.title, 'product_id', a.product_id),
             'b', jsonb_build_object('id', b.id, 'title', b.title, 'product_id', b.product_id)) as x
    from public.decision_conflicts k
    join public.decisions a on a.id = k.decision_id
    join public.decisions b on b.id = k.other_id
    where a.company_id = p_company
      and a.status = 'saved' and a.hidden_at is null and b.status = 'saved' and b.hidden_at is null
      and (p_product is null or a.product_id is not distinct from p_product or a.product_id is null
                             or b.product_id is not distinct from p_product or b.product_id is null)
    limit 50) g;

  return jsonb_build_object('company', v_company, 'guidelines', v_guidelines,
                            'product_decisions', v_products, 'conflicts', v_conflicts);
end $$;

-- What this chat already contributed (so /keep can skip it) ---------------------
create or replace function public.chat_contributions(p_chat_id text)
returns table (keep_id uuid, title text, status text, kept_at timestamptz)
language sql stable set search_path = public as $$
  select d.keep_id, d.title, d.status, d.kept_at
  from public.decisions d
  where d.author_id = auth.uid() and d.chat_id = p_chat_id and public.is_member()
  order by d.kept_at
$$;

-- Hide / restore -------------------------------------------------------------------
create or replace function public.hide_decision(p_id uuid)
returns void language plpgsql security definer set search_path = public as $$
declare v record;
begin
  if not public.is_member() then raise exception 'not a member' using errcode = '42501'; end if;
  select * into v from public.decisions where id = p_id;
  if not found then raise exception 'decision not found'; end if;
  if v.status <> 'saved' then raise exception 'only saved decisions can be hidden; delete the draft instead'; end if;
  if v.author_id <> auth.uid() and not public.is_admin() then
    raise exception 'only the author or an admin can hide this' using errcode = '42501';
  end if;
  update public.decisions set hidden_at = coalesce(hidden_at, now()), hidden_by = coalesce(hidden_by, auth.uid())
   where id = p_id;
end $$;

create or replace function public.restore_decision(p_id uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'only an admin can restore' using errcode = '42501'; end if;
  update public.decisions set hidden_at = null, hidden_by = null where id = p_id;
  if not found then raise exception 'decision not found'; end if;
end $$;

-- Who can call what ----------------------------------------------------------------
revoke all on function public._resolve_company(jsonb, uuid)         from public, anon, authenticated;
revoke all on function public._resolve_product(uuid, jsonb, uuid)   from public, anon, authenticated;
revoke all on function public.push_review(text, timestamptz, jsonb, uuid[])                                     from public, anon;
revoke all on function public.search_decisions(text, extensions.vector, uuid, uuid, boolean, int)               from public, anon;
revoke all on function public.similar_decisions(extensions.vector, uuid, int, uuid[])                           from public, anon;
revoke all on function public.company_brief(uuid, uuid)             from public, anon;
revoke all on function public.chat_contributions(text)              from public, anon;
revoke all on function public.hide_decision(uuid)                   from public, anon;
revoke all on function public.restore_decision(uuid)                from public, anon;
revoke all on function public.is_member()                           from public, anon;
revoke all on function public.is_admin()                            from public, anon;

grant execute on function public.push_review(text, timestamptz, jsonb, uuid[])                                  to authenticated;
grant execute on function public.search_decisions(text, extensions.vector, uuid, uuid, boolean, int)            to authenticated;
grant execute on function public.similar_decisions(extensions.vector, uuid, int, uuid[])                        to authenticated;
grant execute on function public.company_brief(uuid, uuid)          to authenticated;
grant execute on function public.chat_contributions(text)           to authenticated;
grant execute on function public.hide_decision(uuid)                to authenticated;
grant execute on function public.restore_decision(uuid)             to authenticated;
grant execute on function public.is_member()                        to authenticated;
grant execute on function public.is_admin()                         to authenticated;
-- anyone, even before signing in, may ask which schema version is installed (used by `superchat doctor`)
grant execute on function public.superchat_version()                to anon, authenticated;

-- ---------- 0004_history.sql ----------
-- Superchat 0004: history log and automatic member rows
-- Safe to re-run.

-- Every change to a saved decision is recorded (drafts are not: they are private scratch).
create or replace function public._log_decision_change()
returns trigger language plpgsql security definer set search_path = public as $$
declare v_action text;
begin
  if tg_op = 'INSERT' then
    if new.status <> 'saved' then return new; end if;
    insert into public.decision_history (decision_id, action, new_row, actor)
    values (new.id, 'created', to_jsonb(new) - 'embedding' - 'fts', auth.uid());
    return new;
  elsif tg_op = 'UPDATE' then
    if old.status <> 'saved' and new.status <> 'saved' then return new; end if;
    v_action := case
      when old.status <> 'saved' and new.status = 'saved' then 'saved'
      when old.hidden_at is null and new.hidden_at is not null then 'hidden'
      when old.hidden_at is not null and new.hidden_at is null then 'restored'
      else 'edited' end;
    insert into public.decision_history (decision_id, action, old_row, new_row, actor)
    values (new.id, v_action, to_jsonb(old) - 'embedding' - 'fts', to_jsonb(new) - 'embedding' - 'fts', auth.uid());
    return new;
  else
    if old.status = 'saved' then
      insert into public.decision_history (decision_id, action, old_row, actor)
      values (old.id, 'deleted', to_jsonb(old) - 'embedding' - 'fts', auth.uid());
    end if;
    return old;
  end if;
end $$;

drop trigger if exists decisions_history on public.decisions;
create trigger decisions_history
  after insert or update or delete on public.decisions
  for each row execute function public._log_decision_change();

-- Anyone who can sign in (invite-only) becomes a member automatically.
create or replace function public._handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.members (user_id, email, display_name)
  values (new.id, lower(coalesce(new.email, '')), nullif(new.raw_user_meta_data ->> 'name', ''))
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists superchat_new_user on auth.users;
create trigger superchat_new_user
  after insert on auth.users
  for each row execute function public._handle_new_user();

-- People who already exist in the project
insert into public.members (user_id, email)
select u.id, lower(coalesce(u.email, '')) from auth.users u
on conflict (user_id) do nothing;

revoke all on function public._log_decision_change() from public, anon, authenticated;
revoke all on function public._handle_new_user()     from public, anon, authenticated;
