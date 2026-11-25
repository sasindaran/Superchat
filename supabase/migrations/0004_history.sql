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
