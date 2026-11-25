"""
Claude Desktop: add the superchat MCP server to claude_desktop_config.json.

Where that file lives depends on how Claude Desktop was installed:
    Windows (Microsoft Store build): %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude\\
    Windows (downloaded installer) : %APPDATA%\\Claude\\
    macOS                          : ~/Library/Application Support/Claude/
We write to every place where Claude's folder already exists, so the one the app really reads is covered.
"""
import os
import sys
from pathlib import Path

from .common import ConfigError, backup, load_json, python_cmd, save_json

NAME = "superchat"
FILE = "claude_desktop_config.json"


def config_dirs() -> list:
    override = os.environ.get("SUPERCHAT_CLAUDE_DESKTOP_DIR")
    if override:
        return [Path(override)] if Path(override).exists() else []
    found = []
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for pkg in sorted((local / "Packages").glob("Claude_*")) if (local / "Packages").exists() else []:
            d = pkg / "LocalCache" / "Roaming" / "Claude"
            if d.exists():
                found.append(d)
        roaming = Path(os.environ.get("APPDATA", "")) / "Claude"
        if roaming.exists():
            found.append(roaming)
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "Claude"
        if d.exists():
            found.append(d)
    return found


def detected() -> bool:
    return bool(config_dirs())


def entry() -> dict:
    return {"command": python_cmd(), "args": ["-m", "superchat", "mcp"]}


def install() -> list:
    dirs = config_dirs()
    if not dirs:
        raise ConfigError("Claude Desktop does not seem to be installed (no Claude folder found).")
    done = []
    for d in dirs:
        f = d / FILE
        data = load_json(f)
        servers = data.setdefault("mcpServers", {})
        if servers.get(NAME) == entry():
            done.append(f"{f} (already set up)")
            continue
        backup(f)
        servers[NAME] = entry()
        save_json(f, data)
        done.append(str(f))
    return done


def uninstall() -> list:
    done = []
    for d in config_dirs():
        f = d / FILE
        data = load_json(f)
        if NAME in data.get("mcpServers", {}):
            backup(f)
            del data["mcpServers"][NAME]
            save_json(f, data)
            done.append(str(f))
    return done


def status() -> list:
    out = []
    for d in config_dirs():
        f = d / FILE
        try:
            ok = load_json(f).get("mcpServers", {}).get(NAME) == entry()
        except ConfigError:
            ok = False
        out.append((str(f), ok))
    return out
