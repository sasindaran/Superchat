# Design notes

See also [BUILD_PLAN.md](BUILD_PLAN.md) for the original plan.

## Principles
- Only MCP plus the agent: no hosted server, no separate web app, no OS-specific scheduler.
- The database enforces the rules, so a modified tool or a home-made review screen cannot break them.
- Nothing is shared until the author reviews and pushes it.

## Pieces
| Piece | Where |
|---|---|
| Schema, rules, functions | `supabase/migrations/*.sql` (`setup.sql` is generated from them) |
| MCP server and tools | `src/superchat/mcp_server.py`, rules text in `instructions.md` |
| Sign-in (email code) | `auth.py` |
| Capture (local queue, Supabase drafts) | `capture/` |
| Search (keywords + local embeddings) | `search/`, `supabase/migrations/0003_functions.sql` |
| Review and the single push | `review/`, `assets/review/template.html` |
| Claude Code skills and hooks | `assets/claude-code/skills`, `hooks.py` |
| Installers | `agents/` |
| Obsidian copy | `vault.py` |

## Decisions worth knowing
- **`push_review` is `SECURITY DEFINER`.** A saved decision can only come into existence through it; members cannot insert saved rows directly. It checks membership and ownership itself.
- **Embeddings** use `BAAI/bge-small-en-v1.5` (384 numbers) computed locally. The model tag is stored with every vector. Claude writes each decision in clean English at `/keep` time, and that English text is what gets embedded. If the model is unavailable, search falls back to keywords.
- **Claude Desktop** drafts live in Supabase (author-only); **Claude Code** items live in a local queue. The capture target is chosen from the MCP client's name, and can be forced with `SUPERCHAT_CAPTURE=queue|drafts`.
- **Review screen** is an MCP App served by the local Superchat server. It communicates through the MCP host, and needs a client that supports interactive MCP Apps.
- **Strict mode** is a Claude Code hook lock (per session id). In Claude Desktop it is an instruction only: one MCP process is shared by all chats there.
- **The Microsoft Store build of Claude Desktop** keeps its config inside its package folder; the installer writes to every Claude config folder it finds.

## Known limits
- Reminders come from Claude Code hooks; Claude Desktop has none yet.
- `/keep` in Claude Desktop relies on Claude following the MCP prompt/instructions; there is no hard hook.
- Free-tier Supabase pauses after about a week of no use.
