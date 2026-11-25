"""
Claude Code: register the MCP server, install the /keep /keeponly /superchat /superchatall /strict /review skills,
and add the hooks (chat id + reminder, /strict switch, strict lock).
"""
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from .common import ConfigError, backup, load_json, python_cmd, save_json

NAME = "superchat"
SKILLS = ("keep", "keeponly", "superchat", "superchatall", "strict", "review")
MARK = "<!-- superchat -->"
HOOKS = (("SessionStart", None, "session-start"),
         ("UserPromptSubmit", None, "user-prompt"),
         ("PreToolUse", "mcp__superchat__.*", "pre-tool-use"))


def home() -> Path:
    return Path(os.environ.get("SUPERCHAT_CLAUDE_CODE_HOME") or Path.home() / ".claude")


def detected() -> bool:
    return shutil.which("claude") is not None or home().exists()


def hook_command(event: str) -> str:
    return f'"{python_cmd()}" -m superchat hook {event}'


def _is_ours(group: dict) -> bool:
    return any(" -m superchat hook " in (h.get("command") or "") for h in group.get("hooks", []))


def install_skills() -> list:
    out = []
    for name in SKILLS:
        src = resources.files("superchat").joinpath("assets", "claude-code", "skills", name, "SKILL.md").read_text(encoding="utf-8")
        dest = home() / "skills" / name / "SKILL.md"
        if dest.exists():
            existing = dest.read_text(encoding="utf-8")
            if existing == src:
                continue
            if MARK not in existing:
                raise ConfigError(f"{dest} already exists and is not Superchat's. Rename it or remove it, then run setup again.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src, encoding="utf-8")
        out.append(str(dest))
    return out


def install_hooks() -> bool:
    f = home() / "settings.json"
    data = load_json(f)
    hooks = data.setdefault("hooks", {})
    before = repr(hooks)
    for event, matcher, arg in HOOKS:
        groups = [g for g in hooks.get(event, []) if not _is_ours(g)]
        group = {"hooks": [{"type": "command", "command": hook_command(arg)}]}
        if matcher:
            group["matcher"] = matcher
        hooks[event] = groups + [group]
    if repr(hooks) == before:
        return False
    backup(f)
    save_json(f, data)
    return True


def _sandboxed() -> bool:
    """SUPERCHAT_CLAUDE_CODE_HOME redirects our file edits, but `claude mcp ...` always touches the real config."""
    return bool(os.environ.get("SUPERCHAT_CLAUDE_CODE_HOME"))


def register_mcp() -> str:
    if _sandboxed():
        return "skipped (sandbox folder in use; the real `claude mcp` command is not run)"
    claude = shutil.which("claude")
    if not claude:
        return ("the `claude` command was not found. Run this once yourself: "
                f"claude mcp add --scope user {NAME} -- {python_cmd()} -m superchat mcp")
    subprocess.run([claude, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, text=True)
    r = subprocess.run([claude, "mcp", "add", "--scope", "user", NAME, "--", python_cmd(), "-m", "superchat", "mcp"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise ConfigError(f"`claude mcp add` failed: {(r.stderr or r.stdout).strip()[:300]}")
    return "registered with `claude mcp add --scope user`"


def install() -> list:
    steps = [f"MCP server: {register_mcp()}"]
    skills = install_skills()
    steps.append(f"skills: {', '.join(Path(s).parent.name for s in skills)}" if skills else "skills: already installed")
    steps.append("hooks: updated in settings.json" if install_hooks() else "hooks: already installed")
    return steps


def uninstall() -> list:
    steps = []
    claude = None if _sandboxed() else shutil.which("claude")
    if claude:
        r = subprocess.run([claude, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, text=True)
        steps.append("MCP server removed" if r.returncode == 0 else "MCP server was not registered")
    for name in SKILLS:
        d = home() / "skills" / name
        f = d / "SKILL.md"
        if f.exists() and MARK in f.read_text(encoding="utf-8"):
            shutil.rmtree(d)
            steps.append(f"skill removed: {name}")
    f = home() / "settings.json"
    if f.exists():
        data = load_json(f)
        hooks = data.get("hooks", {})
        changed = False
        for event in list(hooks):
            kept = [g for g in hooks[event] if not _is_ours(g)]
            if len(kept) != len(hooks[event]):
                changed = True
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
        if changed:
            if not hooks:
                data.pop("hooks", None)
            backup(f)
            save_json(f, data)
            steps.append("hooks removed")
    return steps


def status() -> dict:
    skills = [n for n in SKILLS if (home() / "skills" / n / "SKILL.md").exists()]
    try:
        hooks = load_json(home() / "settings.json").get("hooks", {})
        hooked = all(any(_is_ours(g) for g in hooks.get(ev, [])) for ev, _, _ in HOOKS)
    except ConfigError:
        hooked = False
    return {"skills": skills, "all_skills": len(skills) == len(SKILLS), "hooks": hooked}
