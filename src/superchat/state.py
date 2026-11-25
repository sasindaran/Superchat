"""Small per-machine state: device id, last push cut-off, reminder throttle."""
import json
import uuid
from datetime import datetime, timezone

from . import paths


def _load() -> dict:
    f = paths.state_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def get(key: str, default=None):
    return _load().get(key, default)


def set_(**kv) -> None:
    s = _load()
    s.update(kv)
    paths.write_private(paths.state_file(), json.dumps(s))


def device_id() -> str:
    d = get("device_id")
    if not d:
        d = "dev-" + uuid.uuid4().hex[:12]
        set_(device_id=d)
    return d


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
