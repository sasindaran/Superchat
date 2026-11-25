"""
Unsaved drafts in Supabase (used by Claude Desktop, so a /keep can be reviewed from any computer).
A draft is visible only to its author. Unticking it in the review deletes it for good.
"""
import re

from .. import state
from ..db import Api
from . import queue

COLUMNS = ("keep_id", "chat_id", "kind", "title", "decision", "condition", "reason",
           "original_text", "source_agent", "folder_key", "kept_at")


def _norm(t) -> str:
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def add(api: Api, items: list, chat_id=None, source_agent=None, folder_key=None) -> dict:
    """Store items as unsaved drafts, skipping anything this chat already contributed."""
    existing = api.select("decisions", select="keep_id,decision,chat_id", chat_id=f"eq.{chat_id}") if chat_id else []
    seen = {_norm(r["decision"]) for r in existing} | {r["keep_id"] for r in existing}
    rows, skipped = [], []
    for raw in items:
        it = queue.prepare(raw, chat_id, source_agent, folder_key)
        if it["keep_id"] in seen or _norm(it["decision"]) in seen:
            skipped.append(it["title"])
            continue
        seen.add(it["keep_id"])
        seen.add(_norm(it["decision"]))
        rows.append({**{k: it.get(k) for k in COLUMNS}, "status": "unsaved"})
    if rows:
        api.insert("decisions", rows)
    waiting = len(api.select("decisions", select="keep_id", status="eq.unsaved"))
    state.set_(draft_count=waiting)          # cached so the reminder needs no network
    return {"added": rows, "skipped": skipped, "waiting": waiting}


def list_own(api: Api) -> list:
    return api.select("decisions", select=",".join(COLUMNS), status="eq.unsaved", order="kept_at.asc")


def for_chat(api: Api, chat_id: str) -> list:
    return api.rpc("chat_contributions", {"p_chat_id": chat_id})
