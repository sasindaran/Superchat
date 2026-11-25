-- Make yourself (the project owner) a Superchat admin.
-- 1. Replace the email below with YOUR sign-in email (any case is fine).
-- 2. Paste into Supabase > SQL Editor and run.
-- Add more admins by adding more rows. Remove an admin by deleting their row.
-- Nobody can read or change this list from the app: only you, here.
insert into public.admin_emails (email)
values (lower('owner@example.com'))
on conflict (email) do nothing;
