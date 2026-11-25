"""
Obsidian copy of the knowledge base: one markdown file per decision.

    <vault>/<Company>/<Company>.md                      index
    <vault>/<Company>/Guidelines/<date> <title>.md      company-wide decisions (no product)
    <vault>/<Company>/<Product>/<date> <title>.md       a product's own decisions

It is a READ-ONLY copy: Supabase is the source of truth and edits made here are overwritten. We only ever delete
files we wrote ourselves (listed in .superchat-manifest.json), never anything else in the vault.
"""
import json
import re
from pathlib import Path

from . import state
from .config import Settings
from .db import Api

MANIFEST = ".superchat-manifest.json"
BANNER = "> [!warning] Read-only copy of Superchat. Edits here are not saved and will be overwritten."


def vault_dir(s: Settings) -> Path:
    return Path(s.vault_dir).expanduser() if s.vault_dir else Path.home() / "Superchat Vault"


def safe(name: str, limit: int = 80) -> str:
    n = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", name or "").strip(" .")
    return re.sub(r"\s+", " ", n)[:limit].strip(" .") or "untitled"


def _yaml(v) -> str:
    return json.dumps(v if v is not None else "", ensure_ascii=False)


def fetch(api: Api) -> dict:
    rows = api.select(
        "decisions",
        select="id,kind,title,decision,condition,reason,original_text,kept_at,source_agent,author_id,"
               "company:companies(id,name),product:products(id,name)",
        status="eq.saved", hidden_at="is.null", order="kept_at.asc")
    people = {m["user_id"]: m.get("display_name") or m["email"] for m in api.select("members", select="user_id,email,display_name")}
    conflicts = api.select("decision_conflicts", select="decision_id,other_id,note")
    return {"rows": rows, "people": people, "conflicts": conflicts}


def render(data: dict) -> dict:
    """{relative path: file text} for the whole vault."""
    rows = [r for r in data["rows"] if r.get("company")]
    by_id = {r["id"]: r for r in rows}
    paths = {}
    for r in rows:
        folder = safe(r["product"]["name"]) if r.get("product") else "Guidelines"
        paths[r["id"]] = f"{safe(r['company']['name'])}/{folder}/{(r['kept_at'] or '')[:10]} {safe(r['title'], 60)}.md"
    # two decisions on the same day with the same title must not overwrite each other
    seen = {}
    for rid, p in list(paths.items()):
        if p in seen:
            paths[rid] = p[:-3] + f" ({rid[:6]}).md"
        seen[paths[rid]] = rid

    def link(rid):
        return f"[[{paths[rid][:-3]}|{by_id[rid]['title']}]]"

    links = {}
    for c in data["conflicts"]:
        if c["decision_id"] in by_id and c["other_id"] in by_id:
            links.setdefault(c["decision_id"], []).append((c["other_id"], c.get("note")))
            links.setdefault(c["other_id"], []).append((c["decision_id"], c.get("note")))

    files = {}
    for r in rows:
        author = data["people"].get(r["author_id"], "")
        conflict_links = [f"{link(o)}" + (f" ({n})" if n else "") for o, n in links.get(r["id"], [])]
        fm = ["---", f"id: {_yaml(r['id'])}", f"kind: {_yaml(r['kind'])}", f"company: {_yaml(r['company']['name'])}",
              f"product: {_yaml(r['product']['name'] if r.get('product') else None)}",
              f"scope: {_yaml('product' if r.get('product') else 'company-wide')}", f"author: {_yaml(author)}",
              f"kept: {_yaml(r['kept_at'])}", f"source: {_yaml(r.get('source_agent'))}",
              f"tags: [superchat, {safe(r['company']['name']).replace(' ', '-')}]", "---"]
        body = [BANNER, "", f"# {r['title']}", "", r["decision"], ""]
        for label, key in (("When it applies", "condition"), ("Why", "reason"), ("Their words", "original_text")):
            if r.get(key):
                body += [f"**{label}:** {r[key]}", ""]
        if conflict_links:
            body += ["## Conflicts", *[f"- {c}" for c in conflict_links], ""]
        files[paths[r["id"]]] = "\n".join(fm + [""] + body)

    companies = {}
    for r in rows:
        companies.setdefault(r["company"]["name"], []).append(r)
    for name, items in companies.items():
        guide = [r for r in items if not r.get("product")]
        prods = {}
        for r in items:
            if r.get("product"):
                prods.setdefault(r["product"]["name"], []).append(r)
        lines = ["---", f"company: {_yaml(name)}", "tags: [superchat]", "---", BANNER, "", f"# {name}", "",
                 f"{len(items)} decisions. Company-wide guidelines apply to every product; a product's own decisions override them.", ""]
        if guide:
            lines += ["## Guidelines (all products)", *[f"- {link(r['id'])}" for r in guide], ""]
        for pname in sorted(prods):
            lines += [f"## {pname}", *[f"- {link(r['id'])}" for r in prods[pname]], ""]
        files[f"{safe(name)}/{safe(name)}.md"] = "\n".join(lines)
    return files


def write(root: Path, files: dict) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    mf = root / MANIFEST
    old = set(json.loads(mf.read_text(encoding="utf-8"))) if mf.exists() else set()
    written = 0
    for rel, text in files.items():
        f = root / rel
        if f.exists() and f.read_text(encoding="utf-8") == text:
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        written += 1
    removed = 0
    for rel in old - set(files):                      # only files WE created earlier
        f = root / rel
        if f.exists():
            f.unlink()
            removed += 1
            for parent in (f.parent, f.parent.parent):   # tidy folders we emptied
                if parent != root and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
    mf.write_text(json.dumps(sorted(files)), encoding="utf-8")
    return {"files": len(files), "written": written, "removed": removed}


def sync(api: Api, settings: Settings) -> dict:
    root = vault_dir(settings)
    result = write(root, render(fetch(api)))
    state.set_(last_vault_sync=state.now_iso())
    return {"vault": str(root), **result}
