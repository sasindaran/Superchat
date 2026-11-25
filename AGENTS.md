# Setting up Superchat (instructions for the AI agent)

You were given this repository's link so you can install **Superchat** for the user on **this computer**. Do every step yourself. Only ask the user for two things: their **work email**, and to **click the sign-in link** that gets emailed to them. Run commands non-interactively. Never edit config files by hand; the commands below do that safely and keep backups.

Superchat is the team's shared decision memory: people keep decisions from their Claude chats (`/keep`), review them, and push them to one shared Supabase, tagged by company and product.

## Steps

1. **Check the tools.**
   - `git --version` must work.
   - `uv --version`. If `uv` is missing, install it:
     - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
     - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
     - Then use the full path (`$HOME/.local/bin/uv`, or `%USERPROFILE%\.local\bin\uv.exe`) if `uv` is not on PATH yet.

2. **Install Superchat** (this repository is private; it uses the user's existing git/GitHub login):
   ```
   uv tool install --python 3.12 --force git+https://github.com/sasindaran/Superchat
   ```
   If this fails with an authentication error, ask the user to sign in to GitHub (`gh auth login`, or sign in via git's credential prompt), then run it again. If the `superchat` command is not found afterwards, run `uv tool update-shell` and use the full path shown by `uv tool dir --bin`.

3. **Set it up** for the apps installed on this computer (Claude Code and Claude Desktop are detected automatically):
   ```
   superchat setup
   ```
   It prints which Supabase project is in use. That is the team's project and is the default; do **not** change it unless the user asks (`superchat setup --url <url>`, and `superchat set --reset-url` to go back).
   If it says the publishable key is not set, the user must get it from the team owner or Supabase (Project Settings > API Keys > publishable key), then run `superchat set --key <key>`.

4. **Sign in.** Ask the user for their work email, then:
   ```
   superchat login --email <email>
   ```
   Supabase emails them a sign-in **link**. Tell them to **click it in a browser on this computer**: it returns to a small page on this machine, Superchat finishes signing in by itself, and the page says "Signed in to Superchat". Then confirm with `superchat whoami` (retry for up to a minute or two). The link works for 15 minutes; run the command again for a new one. Only about 2 sign-in emails per hour are allowed for the whole project, so do not retry in a loop.
   If their email shows a **code** instead of a link (the owner set up custom email), use `superchat login --email <email> --code <code>`.
   If it says the email is not invited, the owner must add it in Supabase first (Authentication > Users).

5. **Check everything.**
   ```
   superchat doctor --deep
   ```
   Report every line to the user. `[ok]` is good. `[FAIL]` needs fixing: read its hint and fix it, or tell the user what to do. (`--deep` downloads a ~65 MB search model the first time; that is expected.)

6. **Finish.** Tell the user to **restart Claude Desktop** and **start a new Claude Code session**. Then explain the commands: `/keep`, `/keeponly <text>`, `/superchat <question>`, `/superchatall <question>`, `/strict`, `/review` (see `docs/commands.md`).

## Rules
- Do not use `pip install` into the system Python. Do not run anything as administrator.
- Do not print or store the user's code, session or keys anywhere except via the commands above.
- To remove everything: `superchat uninstall` (keeps the user's sign-in and data).
- If a step fails, show the exact error text to the user. Do not guess or work around it silently.
