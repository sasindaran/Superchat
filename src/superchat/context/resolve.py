"""
Which company / product does this chat belong to?

Evidence, strongest first:
    1. the project folder is already linked to a company (shared by the whole team)
    2. exactly one company name or alias appears in the text
Anything else is "none": the person is asked. We never guess.
"""
import re


def _find(text: str, names: list) -> bool:
    for n in names:
        n = (n or "").strip()
        if len(n) >= 2 and re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", text, re.I):
            return True
    return False


def resolve(companies: list, folder_link: dict | None, text: str) -> dict:
    """
    companies:   [{id, name, aliases, products:[{id, name, aliases}]}]
    folder_link: {company_id, product_id} or None
    """
    by_id = {c["id"]: c for c in companies}
    text = text or ""

    if folder_link and folder_link.get("company_id") in by_id:
        c = by_id[folder_link["company_id"]]
        p = next((p for p in c.get("products", []) if p["id"] == folder_link.get("product_id")), None)
        return {"strength": "strong", "evidence": "this project folder is linked to it",
                "company": {"id": c["id"], "name": c["name"]},
                "product": {"id": p["id"], "name": p["name"]} if p else None, "candidates": []}

    hits = [c for c in companies if _find(text, [c["name"], *c.get("aliases", [])])]
    if len(hits) == 1:
        c = hits[0]
        ps = [p for p in c.get("products", []) if _find(text, [p["name"], *p.get("aliases", [])])]
        p = ps[0] if len(ps) == 1 else None
        return {"strength": "strong", "evidence": f'"{c["name"]}" is named in the chat',
                "company": {"id": c["id"], "name": c["name"]},
                "product": {"id": p["id"], "name": p["name"]} if p else None, "candidates": []}

    return {"strength": "none",
            "evidence": "several companies are mentioned" if hits else "no known company is mentioned",
            "company": None, "product": None,
            "candidates": [{"id": c["id"], "name": c["name"]} for c in hits]}
