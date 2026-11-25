"""Search and the "does the knowledge base strongly apply?" decision."""
from ..config import Settings
from ..db import Api
from . import embed as emb

# bge-small cosine scores for related text are typically >= 0.75; unrelated text sits near 0.4-0.6.
STRONG_SIMILARITY = 0.78
DUPLICATE_SIMILARITY = 0.92


def vector_literal(v):
    return None if v is None else "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def search(api: Api, settings: Settings, query: str, company_id=None, product_id=None,
           all_companies=False, limit=10) -> dict:
    v = emb.try_embed(settings, [query])
    rows = api.rpc("search_decisions", {
        "p_query": query,
        "p_embedding": vector_literal(v[0]) if v else None,
        "p_company": company_id, "p_product": product_id,
        "p_all": bool(all_companies), "p_limit": limit,
    })
    return {"mode": "keyword+meaning" if v else "keyword only", "results": rows}


def match(api: Api, settings: Settings, question: str, company_id=None, product_id=None) -> dict:
    """Is a stored decision strongly related to this question? Used before answering without a command."""
    res = search(api, settings, question, company_id, product_id, all_companies=company_id is None, limit=5)
    rows = res["results"]

    def strong(r):
        sim = r.get("similarity")
        if sim is not None:
            return sim >= STRONG_SIMILARITY
        return r.get("keyword_rank") == 1 and len(rows) > 0     # keyword-only: only the top hit counts

    hits = [r for r in rows if strong(r)]
    return {"strong": bool(hits), "mode": res["mode"], "hits": hits[:3]}
