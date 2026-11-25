"""
Claude Code hooks (`superchat hook <event>`; Claude Code passes a JSON object on stdin).

    session-start : tells Claude this session's chat id and project folder; adds the reminder if due
    user-prompt   : `/strict` switches strict mode on for this session; adds the reminder if due
    pre-tool-use  : in strict mode, refuses every knowledge-base READ tool (keeping stays allowed)

A hook must never break the user's session: every failure is swallowed and prints nothing.
"""
import json
import re
import sys
from datetime import datetime

from . import config, paths, reminder

# Tools that pull knowledge-base content into an answer. keep / chat_contributions / review / login are NOT here.
READ_TOOLS = ("match", "brief", "search", "resolve_context", "companies")
SERVER = "superchat"


def _safe(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "")[:80]


def marker(session_id: str):
    return paths.strict_dir() / _safe(session_id)


def strict_on(session_id: str) -> None:
    marker(session_id).write_text("strict", encoding="utf-8")


def strict_off(session_id: str) -> None:
    m = marker(session_id)
    if m.exists():
        m.unlink()


def is_strict(session_id: str) -> bool:
    return bool(session_id) and marker(session_id).exists()


def _context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def handle(event: str, payload: dict, now: datetime | None = None) -> dict | None:
    """Returns the JSON to print, or None to print nothing."""
    now = now or datetime.now()
    sid = payload.get("session_id") or ""
    s = config.load()

    if event == "session-start":
        lines = [f"superchat chat id: {sid}", f"superchat folder: {payload.get('cwd') or ''}"]
        if is_strict(sid):
            lines.append("Strict mode is ON for this session: do not use the Superchat knowledge base to answer.")
        note = reminder.message(now, s)
        if note:
            lines.append(note)
        return _context("SessionStart", "\n".join(lines))

    if event == "user-prompt":
        prompt = (payload.get("prompt") or "").strip().lower()
        if prompt.split(" ")[0] == "/strict":
            strict_on(sid)
            return _context("UserPromptSubmit",
                            "Strict mode is now ON for the rest of this session: never use the Superchat knowledge base "
                            "to answer. Confirm once: \"Strict mode: the knowledge base won't be used in this session.\" "
                            "/keep and /keeponly still work.")
        note = reminder.message(now, s)
        return _context("UserPromptSubmit", note) if note else None

    if event == "pre-tool-use":
        name = payload.get("tool_name") or ""
        prefix = f"mcp__{SERVER}__"
        if name.startswith(prefix) and name[len(prefix):] in READ_TOOLS and is_strict(sid):
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": "Strict mode is on for this session: the Superchat knowledge base is not "
                                            "used to answer. (Keeping with /keep still works.)"}}
        return None
    return None


def run(event: str) -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        out = handle(event, payload)
        if out:
            print(json.dumps(out))
    except Exception:
        pass
    return 0
