"""
Local embeddings (no API key, no network after the first model download).

Everyone must use the same model, or their vectors cannot be compared. The model's tag is
stored with every vector and a push from a machine with a different model is refused.
"""
import threading

from .. import paths
from ..config import Settings

_lock = threading.Lock()
_models: dict = {}


class EmbeddingUnavailable(Exception):
    pass


def _model(settings: Settings):
    with _lock:
        if settings.embedding_model not in _models:
            try:
                from fastembed import TextEmbedding
                _models[settings.embedding_model] = TextEmbedding(
                    model_name=settings.embedding_model, cache_dir=str(paths.models_dir()), threads=1)
            except Exception as e:  # missing package, blocked download, ...
                raise EmbeddingUnavailable(f"embedding model not available: {e}") from e
        return _models[settings.embedding_model]


def embed(settings: Settings, texts: list) -> list:
    """One vector (list of floats) per text."""
    if not texts:
        return []
    m = _model(settings)
    out = [[float(x) for x in v] for v in m.embed(list(texts))]
    if out and len(out[0]) != settings.embedding_dim:
        raise EmbeddingUnavailable(
            f"model produced {len(out[0])} numbers but the team database expects {settings.embedding_dim}")
    return out


def try_embed(settings: Settings, texts: list):
    """Like embed(), but returns None instead of raising, so search can fall back to keywords."""
    try:
        return embed(settings, texts)
    except EmbeddingUnavailable:
        return None


def text_for_item(item: dict) -> str:
    """What gets embedded for a decision: its clean-English fields, not the original wording."""
    parts = [item.get("title"), item.get("decision"), item.get("condition"), item.get("reason")]
    return ". ".join(p.strip() for p in parts if p and p.strip())
