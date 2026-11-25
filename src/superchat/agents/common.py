"""Shared helpers for editing other apps' config files safely."""
import json
import os
import shutil
import sys
import time
from pathlib import Path


class ConfigError(Exception):
    pass


def python_cmd() -> str:
    """The Python that runs superchat (inside its own tool environment); stable and not dependent on PATH."""
    return sys.executable.replace("\\", "/")


def load_json(path: Path) -> dict:
    """A JSON object from a file; {} when missing or empty. Refuses (never overwrites) a file it cannot parse."""
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ConfigError(f"{path} is not valid JSON ({e}); fix or remove it and run setup again. Nothing was changed.") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not hold a JSON object. Nothing was changed.")
    return data


def backup(path: Path) -> Path | None:
    """Copy a file next to itself before the first change we make to it."""
    if not path.exists():
        return None
    b = path.with_name(f"{path.name}.superchat-backup-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, b)
    return b


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
