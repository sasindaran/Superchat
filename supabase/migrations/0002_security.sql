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
