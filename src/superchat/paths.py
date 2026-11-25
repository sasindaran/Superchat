"""Per-OS folders. Everything Superchat keeps on a machine lives under home()."""
import os
import sys
from pathlib import Path


def home() -> Path:
    override = os.environ.get("SUPERCHAT_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "superchat"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "superchat"
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "superchat"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path: return home() / "settings.json"
def session_file() -> Path: return home() / "session.json"
def queue_file() -> Path: return home() / "queue.jsonl"
def state_file() -> Path: return home() / "state.json"
def models_dir() -> Path:
    d = home() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def strict_dir() -> Path:
    d = home() / "strict"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_private(path: Path, text: str) -> None:
    """Write a file only the current user can read (best effort on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
