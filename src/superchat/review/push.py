"""The one Push: validate, embed locally, save everything in a single database transaction."""
from pydantic import ValidationError

from .. import state
from ..capture import queue
from ..config import Settings
from ..db import Api, ApiError
from ..search import embed as emb
from .contract import PushPayload


class PushRefused(Exception):
    pass


def push(api: Api, settings: Settings, payload: dict) -> dict:
    try:
        p = PushPayload.model_validate(payload)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:5])
        raise PushRefused(f"Nothing was pushed. The review is incomplete: {problems}") from e

    for it in p.items:                                  # company is required; product may be empty
        if not it.company.id and not (it.company.name or "").strip():
            raise PushRefused(f"Nothing was pushed. '{it.title}' has no company.")

    vectors = emb.try_embed(settings, [emb.text_for_item(i.model_dump()) for i in p.items]) if p.items else []
    rows = []
    for n, it in enumerate(p.items):
        d = it.model_dump(exclude_none=False)
        d["company"] = {k: v for k, v in it.company.model_dump().items() if v}
        d["product"] = {k: v for k, v in it.product.model_dump().items() if v} if it.product else None
        d["embedding"] = [float(x) for x in vectors[n]] if vectors else None
        d["embedding_model"] = settings.embedding_tag if vectors else None
        d["conflicts"] = [c.model_dump() for c in it.conflicts]
        rows.append(d)

    try:
        result = api.rpc("push_review", {
            "p_device_id": state.device_id(), "p_cutoff": p.cutoff,
            "p_items": rows, "p_remove_keep_ids": p.remove_keep_ids})
    except ApiError as e:
        raise PushRefused(f"Nothing was pushed: {e}. Your list is unchanged; fix it and push again.") from e

    queue.remove([i.keep_id for i in p.items] + list(p.remove_keep_ids))
    state.set_(last_cutoff=p.cutoff, last_push=state.now_iso(),
               draft_count=max(0, int(state.get("draft_count", 0) or 0) - len(p.remove_keep_ids) - len(p.items)))
    result["embeddings"] = "stored" if vectors else "skipped (model unavailable; keyword search only)"
    return result
