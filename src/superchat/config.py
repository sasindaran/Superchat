"""
Settings, lowest to highest priority:
    1. defaults.json shipped in the package (the team's Supabase; remove before open-sourcing)
    2. the user's settings.json
    3. environment variables (SUPERCHAT_SUPABASE_URL, SUPERCHAT_SUPABASE_KEY, ...)
"""
import json
import os
from dataclasses import dataclass, field
from importlib import resources

from . import paths

ENV_MAP = {
    "SUPERCHAT_SUPABASE_URL": "supabase_url",
    "SUPERCHAT_SUPABASE_KEY": "supabase_key",
    "SUPERCHAT_CAPTURE": "capture_mode",
    "SUPERCHAT_VAULT": "vault_dir",
}


@dataclass
class Settings:
    supabase_url: str = ""
    supabase_key: str = ""
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_tag: str = "bge-small-en-v1.5"
    embedding_dim: int = 384
    schema_version: str = "1"
    capture_mode: str = "auto"          # auto | queue | drafts
    vault_dir: str = ""
    reminder_start_hour: int = 15       # weekdays 3pm ...
    reminder_end_hour: int = 18         # ... to 6pm, local time
    extra: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


def _packaged() -> dict:
    return json.loads(resources.files("superchat").joinpath("defaults.json").read_text(encoding="utf-8"))


def _user() -> dict:
    f = paths.settings_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def load() -> Settings:
    merged = {**_packaged(), **_user()}
    for env, key in ENV_MAP.items():
        if os.environ.get(env):
            merged[key] = os.environ[env]
    known = {k: v for k, v in merged.items() if k in Settings.__dataclass_fields__ and k != "extra"}
    s = Settings(**known)
    s.supabase_url = s.supabase_url.rstrip("/")
    return s


def save_user(**changes) -> None:
    current = _user()
    current.update({k: v for k, v in changes.items() if v is not None})
    paths.write_private(paths.settings_file(), json.dumps(current, indent=2))


def unset_user(*keys: str) -> None:
    current = _user()
    for k in keys:
        current.pop(k, None)
    paths.write_private(paths.settings_file(), json.dumps(current, indent=2))
