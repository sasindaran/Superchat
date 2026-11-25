"""
Local queue for kept decisions (Claude Code and anything else on this machine).
One JSON object per line. Everything in the queue is waiting for review; a successful
push removes what was reviewed.
"""
import json
import re
import uuid
from datetime import datetime, timezone

from .. import paths
from ..redact import redact

TEXT_FIELDS = ("title", "decision", "condition", "reason", "original_text")


def _norm(t) -> str:
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_all() -> list:
    f = paths.queue_file()
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn line must never break the queue
    return out


def _write_all(items: list) -> None:
    paths.write_private(paths.queue_file(), "".join(json.dumps(i) + "\n" for i in items))


def prepare(item: dict, chat_id=None, source_agent=None, folder_key=None) -> dict:
    """Normalise one item and mask secrets. Used for the queue and for Supabase drafts."""
    kind = item.get("kind") or "decision"
    if kind not in ("decision", "key_note"):
        raise ValueError(f"kind must be 'decision' or 'key_note', not {kind!r}")
    out = {
        "keep_id": item.get("keep_id") or str(uuid.uuid4()),
        "chat_id": item.get("chat_id") or chat_id,
        "kind": kind,
        "source_agent": item.get("source_agent") or source_agent,
        "folder_key": item.get("folder_key") or folder_key,
        "kept_at": item.get("kept_at") or _now(),
    }
    for f in TEXT_FIELDS:
        out[f] = redact((item.get(f) or "").strip()) or None
    if not out["title"] or not out["decision"]:
        raise ValueError("every item needs a title and a decision")
    for opt in ("company_suggestion", "product_suggestion", "evidence"):
        if item.get(opt) is not None:
            out[opt] = item[opt]
    return out


def add(items: list, chat_id=None, source_agent=None, folder_key=None) -> dict:
    """Queue items, skipping any already queued for the same chat with the same decision text."""
    existing = read_all()
    seen = {(i.get("chat_id"), _norm(i.get("decision"))) for i in existing} | {i["keep_id"] for i in existing}
    added, skipped = [], []
    for raw in items:
        it = prepare(raw, chat_id, source_agent, folder_key)
        key = (it["chat_id"], _norm(it["decision"]))
        if it["keep_id"] in seen or key in seen:
            skipped.append(it["title"])
            continue
        seen.add(key)
        seen.add(it["keep_id"])
        existing.append(it)
        added.append(it)
    if added:
        _write_all(existing)
    return {"added": added, "skipped": skipped, "waiting": len(existing)}


def for_chat(chat_id: str) -> list:
    return [i for i in read_all() if i.get("chat_id") == chat_id]


def remove(keep_ids) -> int:
    ids = set(keep_ids)
    items = read_all()
    kept = [i for i in items if i["keep_id"] not in ids]
    if len(kept) != len(items):
        _write_all(kept)
    return len(items) - len(kept)


def count() -> int:
    return len(read_all())
