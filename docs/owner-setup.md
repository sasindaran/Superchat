# Owner setup (one time)

You need a Supabase project (the free tier is enough). Do these once; then invite people.

## 1. Install the database
Put your credentials in a file called `superchat.env` (copy `superchat.env.example`; it is git-ignored, so it is never committed). Fill in the database password (Supabase > Project Settings > Database > **Reset database password**) and your sign-in email. Then, from the folder that holds that file:

```
superchat admin status                     # read-only: shows what is in the database now
superchat admin init                       # installs Superchat (safe to run again)
superchat admin init --reset --yes         # ONLY if the database holds an older app's data: wipes the `public` schema first
```

`--reset` removes everything in the `public` schema (the old tables, functions and extensions). It never touches your Supabase **sign-in users** or any other schema. The email in `SUPERCHAT_ADMIN_EMAIL` (or `--admin-email`) becomes an admin.

No database password handy? Paste [`supabase/setup.sql`](../supabase/setup.sql) into Supabase > **SQL Editor** and run it, then run [`supabase/seed_admin.sql`](../supabase/seed_admin.sql) with your email. If the project holds an older app's data, the old `vector` extension must be dropped first, which is what `--reset` does.

## 2. Lock sign-up and make the email show a code
1. **Authentication > Sign In / Providers**: turn **off** "Allow new users to sign up" (so only people you invite can get in). Keep **Email** enabled.
2. **Authentication > Email Templates**: open the **Magic Link** template (and **Confirm signup** if present) and make sure the body contains the six-digit code, for example:
   ```html
   <p>Your Superchat code is: <b>{{ .Token }}</b></p>
   ```
   (Superchat signs people in with this code, not with a link.)
3. Supabase's built-in email sender has a low hourly limit on the free tier. If invites or codes stop arriving, add your own SMTP under **Authentication > SMTP Settings**.

## 3. Invite the team
**Authentication > Users > Add user > Send invitation** (or "Create new user" with *Auto Confirm User*). Everyone you add can read all saved decisions and can only change their own. Employees are *app users*, **not** Supabase team members: never add them to the Supabase project itself, because that gives dashboard access that skips the rules.

## 4. Give the team the key
In **Project Settings > API Keys** copy the **publishable key** (starts with `sb_publishable_`). It is not a secret: put it in `src/superchat/defaults.json` (`supabase_key`) in this private repository, so setup needs nothing from employees but their email.

**Never** share or commit the `service_role` / secret key or the database password.

## Admin rules
| Who | Can |
|---|---|
| Any member | read all saved decisions; add their own; edit or hide **their own** |
| Admin (email in `admin_emails`) | also edit or hide anyone's, and **restore** hidden decisions |
| Nobody (from the app) | read or change the admin list, or hard-delete a saved decision |

To remove a person: Authentication > Users > delete. Their saved decisions stay.

## Free tier note
Supabase pauses a free project after about a week with no activity. Daily use keeps it awake.
