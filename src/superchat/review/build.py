"""Build the review list: everything kept and not yet pushed, with suggestions and look-alikes."""
from ..capture import drafts, queue
from ..config import Settings
from ..context.resolve import resolve
from ..db import Api
from ..search import embed as emb
from ..search.hybrid import vector_literal
from .. import state

SIMILAR_FLOOR = 0.75   # below this a saved decision is not worth showing as a look-alike


def companies(api: Api) -> list:
    rows = api.select("companies", select="id,name,aliases,products(id,name,aliases,hidden_at)",
                      hidden_at="is.null", order="name.asc")
    for c in rows:
        c["products"] = sorted((p for p in c.get("products") or [] if not p.get("hidden_at")), key=lambda p: p["name"].lower())
    return rows


def build(api: Api, settings: Settings) -> dict:
    built_at = state.now_iso()
    cos = companies(api)

    entries = [dict(i, source="queue") for i in queue.read_all()]
    own_drafts = drafts.list_own(api)
    state.set_(draft_count=len(own_drafts))
    entries += [dict(d, source="draft") for d in own_drafts]
    entries.sort(key=lambda e: e.get("kept_at") or "")

    links = {}
    for key in {e.get("folder_key") for e in entries if e.get("folder_key")}:
        found = api.select("folder_links", select="company_id,product_id", folder_key=f"eq.{key}")
        links[key] = found[0] if found else None

    vectors = emb.try_embed(settings, [emb.text_for_item(e) for e in entries]) if entries else []
    items = []
    for n, e in enumerate(entries):
        text = " ".join(filter(None, [e.get("title"), e.get("decision"), e.get("original_text")]))
        sug = resolve(cos, links.get(e.get("folder_key")), text)
        similar = []
        if vectors:
            for r in api.rpc("search_decisions", {"p_query": emb.text_for_item(e), "p_embedding": vector_literal(vectors[n]),
                                                   "p_all": True, "p_limit": 3}):
                if (r.get("similarity") or 0) >= SIMILAR_FLOOR:
                    similar.append({"id": r["id"], "title": r["title"], "decision": r["decision"], "company": r["company"],
                                    "product": r.get("product"), "similarity": round(r["similarity"], 3),
                                    "author_email": r.get("author_email")})
        items.append({
            "keep_id": e["keep_id"], "source": e["source"], "chat_id": e.get("chat_id"), "kind": e.get("kind") or "decision",
            "title": e["title"], "decision": e["decision"], "condition": e.get("condition"), "reason": e.get("reason"),
            "original_text": e.get("original_text"), "kept_at": e.get("kept_at"),
            "source_agent": e.get("source_agent"), "folder_key": e.get("folder_key"),
            "suggestion": {"company": sug["company"], "product": sug["product"], "evidence": sug["evidence"],
                           "strength": sug["strength"]},
            "similar": similar, "selected": True,
        })
    return {"built_at": built_at, "cutoff": built_at, "items": items,
            "companies": [{"id": c["id"], "name": c["name"], "aliases": c.get("aliases") or [],
                           "products": [{"id": p["id"], "name": p["name"]} for p in c["products"]]} for c in cos]}
