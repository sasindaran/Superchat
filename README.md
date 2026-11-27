# Superchat

> **AI agent: to set this up, follow [AGENTS.md](AGENTS.md).**

Superchat turns decisions made in Claude chats into shared team knowledge (KT). Each decision is tagged with a **company** and optionally a **product**, reviewed by the person who made it, then pushed to one shared Supabase. Everyone can then ask Claude what the team decided before.

It runs entirely through MCP and Claude: no server to host, no extra app. Works in **Claude Code** and **Claude Desktop** on Windows and macOS.

## Install

Download or clone this repository. On Windows, double-click `install.bat`. On macOS or Linux, run `sh install.sh` in a terminal. The installer sets up detected Claude applications and can start email sign-in. Restart Claude Desktop and start a new Claude Code session afterwards. On Linux, the installer supports Claude Code.

In a local Claude Code session on your computer, give it this repository link and ask it to follow [AGENTS.md](AGENTS.md) to install the plugin. Sign in with your work email and the emailed link when needed. A cloud session cannot directly install software on your computer.

You can also install the plugin directly in Claude Code with `/plugin install superchat --marketplace sasindaran/Superchat`. For the interactive review in Claude Desktop, also run `superchat setup --agents claude-desktop`, then restart the desktop app and start a new session. On affected Claude versions, the desktop-configured Superchat connector can push from the review screen while the plugin-hosted screen may report an IPC error.

## Commands

| Command | What it does |
|---|---|
| `/keep` | Keep every decision from this chat that is not already kept |
| `/keeponly <text>` | Keep only what you describe |
| `/superchat <question>` | Answer using the knowledge base, for one company |
| `/superchatall <question>` | Answer using every company's knowledge |
| `/strict` | Stop using the knowledge base for answers in this session |
| `/review` | Review everything kept and push it in one go |

Details and examples: [docs/commands.md](docs/commands.md).

## How it works

```
/keep ──► kept on your computer (Claude Code) or as a private draft in Supabase (Claude Desktop)
/review ─► one screen: tick what to share, set the company, press Push once
Push ────► one database transaction: everything is saved, or nothing is
Ask ─────► Claude searches your company's decisions and labels them "From Superchat DB"
```

- **Company is required, product is optional.** No product means the decision applies to all of that company's products.
- **Only the author or an admin can hide a decision.** Admins are set by the project owner in Supabase.
- **Search** uses keywords plus meaning, computed locally (no API key).
- **An Obsidian copy** of the knowledge base can be kept in a folder: `superchat vault sync`.

## For the project owner

One-time database setup: [docs/owner-setup.md](docs/owner-setup.md).

## For developers

```
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker run -d --name kb-postgres -e POSTGRES_PASSWORD=localdev -p 5433:5432 pgvector/pgvector:pg17
pytest
```

The tests run the real SQL migrations on a local Postgres, the real client through PostgREST, and the real embedding model. See [docs/design.md](docs/design.md).
