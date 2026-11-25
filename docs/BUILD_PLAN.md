> **Status:** built and tested; see docs/design.md for what exists. This file is the original plan.

# Superchat — Build Plan (handoff)

Scope for this build: **Claude Code + Claude Desktop only**. Codex/Cursor are out for now (no config writers, no assets for them). Architecture is frozen as agreed — if anything below cannot work as written, STOP and ask the user before changing the design.

## Hard rules for whoever builds this
- **No Claude attribution anywhere**: no `Co-Authored-By` trailer, no "Generated with Claude Code", no Claude credit in files. Plain commit messages.
- GitHub: **private** repo on the user's *other* GitHub account, via `git`/`gh` CLI. The user runs `gh auth login` themselves.
- Python **3.12** (fastembed/onnxruntime may lag 3.14). Pin `mcp>=1.28,<2` (mcp 2.x renamed FastMCP and breaks the API).
- Never print secrets. Never put the Supabase `service_role` key or the DB password in the repo or on employee machines.
- `uv` is **not on PATH** on this machine; `gh` is installed but **not logged in**; Docker Desktop is installed (start it when needed); Node/npx present; Supabase CLI not installed (use `npx supabase`).

## Known facts
- Existing Supabase project ref: `trhvoeqtbuoebdozeiko` → default URL `https://trhvoeqtbuoebdozeiko.supabase.co` (region ap-northeast-2).
- Publishable key: in `company-knowledge-mcp/.env` as `SUPABASE_PUBLISHABLE_KEY` (read it without echoing; it is safe to ship in the private repo's `superchat.defaults.json`).
- The DB password in that `.env` was rejected earlier — do not rely on it.
- Folder: this `superchat/` lives inside `company-knowledge-mcp-fresh/` as its own git repo; add `superchat/` to the parent's `.git/info/exclude` (do not edit the parent's tracked files).

## Commands (final)
| Command | Behaviour |
|---|---|
| `/keep` | Every decision/key note in the whole chat not already kept or pushed from this chat (MCP `chat_contributions` tells Claude what to skip; duplicate check catches the rest). Works in strict. |
| `/keeponly <text>` | Only what the user describes. Works in strict. |
| `/superchat [q]` | Must use the KB, one company (message name → linked folder → names in chat → ask). Label everything. |
| `/superchatall [q]` | All companies, each result labelled with its company. |
| `/strict` | Rest of session: KB never used for answers (Claude Code: hook lock; Desktop: instruction). `/keep` still works. |
| `/review` | Open the review now. |
| no command | Use KB only if `match` says strong; always label "From Superchat DB". |
Chat id: Claude Code session id (session-start hook); Desktop: first `/keep` prints `superchat chat: sc-xxxx`, later keeps reuse it.
Where kept items wait: Claude Code → local queue; Claude Desktop → unsaved draft in Supabase (author-only).

## Data rules
Company required, product optional (empty = company-wide, red warning). Conflicts shown, never block. One Push for the whole list; unticked items deleted for good; list = everything kept after this device's last cut-off (cut-off = moment the list was built); no expiry. Admins = `admin_emails` table edited by the owner; owner seeded. Everyone reads saved decisions; only author or admin edits/hides; admin restores.

---

## Milestone 1 — Supabase (first)
1. Write `supabase/migrations/0001_core.sql … 0004_history.sql`, plus `supabase/setup.sql` (all-in-one) and `supabase/seed_admin.sql`. Include `superchat_version()` returning the schema version (used by `doctor`).
   - Tables: members, admin_emails, companies, products, folder_links, decisions (keep_id unique, status unsaved|saved, embedding vector(384), embedding_model, fts index, CHECK saved ⇒ company), decision_conflicts, decision_history, push_batches.
   - RLS on every table; `is_member()`, `is_admin()` (SECURITY DEFINER, read admin_emails by JWT email).
   - Functions: `push_review` (one transaction, SECURITY INVOKER, idempotent by keep_id), `search_decisions` (keyword + vector merged), `similar_decisions`, `company_brief`, `chat_contributions`, `hide_decision`, `restore_decision`.
   - Trigger: auth.users insert → members row; history trigger on decisions.
2. Test locally: `npx supabase start` (Docker) → apply migrations → `tests/test_security_rules.py`, `tests/test_push.py` must pass (author / other member / admin matrix, all-or-nothing, retry-safe).
3. Apply to the real project — **ask the user which way**: (a) user pastes `setup.sql` into the SQL editor (recommended, no password) or (b) Supabase connector from the owner account.
4. User does in the dashboard (give them this checklist):
   - Authentication → turn OFF "Allow new users to sign up"; email provider ON.
   - Email template "Magic Link"/OTP → include the 6-digit `{{ .Token }}` code.
   - Users → add the owner + one test employee (auto-confirm).
   - Run `seed_admin.sql` with the owner email.
5. Verify live: `superchat_version()` answers via the publishable key; an anonymous request reads 0 rows; test user signs in with a code; one insert/read works under RLS.
   - [verify] OTP sign-in for dashboard-created users; built-in email hourly limit (if hit: free SMTP).

## Milestone 2 — The package and MCP (local)
Build in phase order; Codex/Cursor parts skipped.
1. Core: `config.py` (env > user settings > `superchat.defaults.json`), `paths.py`, `auth.py` (email code via MCP + CLI flags, shared session per machine), `db.py`, `cli.py doctor`.
   - `doctor` must check: default URL resolves and answers (`/auth/v1/health` with the publishable key) → **"default Supabase URL exists"**; `superchat_version()` matches; signed in; model available; Claude Code + Desktop configs present.
2. MCP server: tools (login, verify_code, whoami, logout, keep, chat_contributions, resolve_context, match, brief, search, companies, products, review_list, push_review, review_status, vault_sync), prompts, `instructions.md`, redaction.
3. Search: fastembed `bge-small-en-v1.5` (384), lazy load, keyword fallback, model name stored with each vector.
4. Review: `review/contract.md`, JSON schemas, `template.html`; Claude Desktop artifact calls the local MCP (`host:superchat`) for companies + Push; text review fallback.
5. Claude Code assets: skills (keep, keeponly, superchat, superchatall, strict, review) + hooks (strict lock, weekday 15:00–18:00 local reminder, chat id at session start).
6. Obsidian vault sync.
7. `agents/claude_code.py`, `agents/claude_desktop.py` (back up config before editing; Windows `%APPDATA%\Claude\claude_desktop_config.json`, Mac `~/Library/Application Support/Claude/claude_desktop_config.json` [verify]).
8. `superchat setup` / `uninstall`, all non-interactive with flags.

## Milestone 3 — GitHub repo
1. `superchat.defaults.json` = default URL above + publishable key.
2. `AGENTS.md` (setup steps any agent can run), `CLAUDE.md` → "Follow AGENTS.md", `README.md`, `docs/*`.
3. `git init`, plain commits (no attribution), user runs `gh auth login` with the other account, then `gh repo create <account>/superchat --private --source=. --push`.

## Milestone 4 — "Paste the link" test
1. **Claude Code** (fresh terminal, empty folder): paste the repo link + "set this up". Expect: reads AGENTS.md → installs uv → `uv tool install --python 3.12 git+https://github.com/<account>/superchat` → `superchat setup` (shows default URL, user may edit) → **asks for email, then the emailed code** → `doctor` all green incl. default URL check → asks user to restart Claude Desktop.
2. **Claude Desktop**: paste the same link in a normal chat and record what happens.
   - Expected limits [verify]: a normal Desktop chat has no shell to run installers, and a private GitHub page can't be fetched without login. If so, **stop and ask the user** which route to use: (a) run setup from the Code tab of the Claude desktop app / Claude Code (which also configures Desktop), or (b) ship a one-click Claude Desktop extension (.mcpb) in GitHub Releases.
3. After restart: Desktop lists superchat tools; `/keep` → draft; `/review` artifact opens in the desktop app, Push works; Claude Code `/keep` → queue; `/strict` blocks reads.

## Milestone 5 — Pilot
Owner + one employee for a week; fix issues; then the team.

## Phase-0 checks (do first, record results in docs/design.md)
1. Claude Code skill names come out exactly `/keep` etc.
2. How Claude Desktop shows MCP prompts (commands vs attach menu).
3. Artifact in the Claude desktop app can call the local MCP (permission prompt, Push).
4. Claude Desktop scheduled tasks can open the review (else: Code hook reminder only).
5. fastembed on Python 3.12 Windows (+ Mac tester), download size.
6. Supabase code sign-in for dashboard-created users; email limits.
7. Claude Desktop config path/format; what a normal Desktop chat does with a pasted private-repo link.
