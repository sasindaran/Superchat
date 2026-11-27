"""Installers (Claude Code, Claude Desktop), the hooks, strict mode and the reminder. Never touches real settings."""
import json
import subprocess
import sys
from datetime import datetime

import pytest

from superchat import cli, config, hooks, reminder, state
from superchat.agents import claude_code, claude_desktop
from superchat.agents.common import ConfigError
from superchat.capture import queue


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERCHAT_HOME", str(tmp_path / "sc"))
    monkeypatch.setenv("SUPERCHAT_CLAUDE_CODE_HOME", str(tmp_path / "dot-claude"))
    monkeypatch.setenv("SUPERCHAT_CLAUDE_DESKTOP_DIR", str(tmp_path / "desktop" / "Claude"))
    (tmp_path / "desktop" / "Claude").mkdir(parents=True)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)     # never run the real `claude` CLI
    return tmp_path


def cc_settings(sandbox):
    return sandbox / "dot-claude" / "settings.json"


# ---- Claude Code installer -----------------------------------------------------------------------------

def test_install_adds_skills_and_hooks_and_keeps_existing_settings(sandbox):
    f = cc_settings(sandbox)
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"model": "sonnet", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    steps = claude_code.install()
    assert any("skills:" in s for s in steps) and any("hooks:" in s for s in steps)
    data = json.loads(f.read_text())
    assert data["model"] == "sonnet" and "Stop" in data["hooks"]                       # untouched
    assert set(data["hooks"]) == {"Stop", "SessionStart", "UserPromptSubmit", "PreToolUse"}
    pre = data["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "mcp__superchat__.*" and "superchat hook pre-tool-use" in pre["hooks"][0]["command"]
    assert list(f.parent.glob("settings.json.superchat-backup-*"))                      # backed up first
    for name in claude_code.SKILLS:
        body = (sandbox / "dot-claude" / "skills" / name / "SKILL.md").read_text()
        assert body.startswith("---\nname: " + name) and "disable-model-invocation: true" in body


def test_install_twice_changes_nothing_and_never_duplicates(sandbox):
    claude_code.install()
    before = cc_settings(sandbox).read_text()
    steps = claude_code.install()
    assert cc_settings(sandbox).read_text() == before
    assert "skills: already installed" in steps and "hooks: already installed" in steps
    assert all(len(g) == 1 for g in json.loads(before)["hooks"].values())


def test_install_refuses_to_overwrite_someone_elses_skill(sandbox):
    d = sandbox / "dot-claude" / "skills" / "keep"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: keep\n---\nmy own keep command")
    with pytest.raises(ConfigError, match="not Superchat's"):
        claude_code.install_skills()
    assert "my own keep command" in (d / "SKILL.md").read_text()


def test_unparseable_settings_are_never_overwritten(sandbox):
    f = cc_settings(sandbox)
    f.parent.mkdir(parents=True)
    f.write_text("{ this is not json")
    with pytest.raises(ConfigError, match="Nothing was changed"):
        claude_code.install_hooks()
    assert f.read_text() == "{ this is not json"


def test_uninstall_removes_only_ours(sandbox):
    f = cc_settings(sandbox)
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"model": "sonnet", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    other = sandbox / "dot-claude" / "skills" / "mine"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("mine")
    claude_code.install()
    assert claude_code.status() == {"skills": list(claude_code.SKILLS), "all_skills": True, "hooks": True}
    steps = claude_code.uninstall()
    assert "hooks removed" in steps
    assert json.loads(f.read_text()) == {"model": "sonnet", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    assert (other / "SKILL.md").exists() and not (sandbox / "dot-claude" / "skills" / "keep").exists()
    assert claude_code.status()["hooks"] is False


# ---- Claude Desktop installer ----------------------------------------------------------------------------

def test_windows_desktop_config_detects_current_store_data(sandbox, monkeypatch):
    monkeypatch.delenv("SUPERCHAT_CLAUDE_DESKTOP_DIR")
    monkeypatch.setattr(claude_desktop.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(sandbox / "local"))
    monkeypatch.setenv("APPDATA", str(sandbox / "roaming"))
    current = sandbox / "local" / "Claude-Data" / "claude_example"
    legacy = sandbox / "local" / "Packages" / "Claude_example" / "LocalCache" / "Roaming" / "Claude"
    current.mkdir(parents=True)
    legacy.mkdir(parents=True)
    assert claude_desktop.config_dirs() == [current, legacy]
    assert len(claude_desktop.install()) == 2
    assert (current / claude_desktop.FILE).exists()
    assert (legacy / claude_desktop.FILE).exists()

def test_desktop_install_creates_config_and_keeps_other_servers(sandbox):
    f = sandbox / "desktop" / "Claude" / claude_desktop.FILE
    f.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    claude_desktop.install()
    data = json.loads(f.read_text())
    assert data["mcpServers"]["other"] == {"command": "x"} and data["theme"] == "dark"
    assert data["mcpServers"]["superchat"] == {"command": sys.executable.replace("\\", "/"), "args": ["-m", "superchat", "mcp"]}
    assert list(f.parent.glob("*.superchat-backup-*"))
    assert claude_desktop.status() == [(str(f), True)]


def test_desktop_install_from_nothing_and_twice(sandbox):
    f = sandbox / "desktop" / "Claude" / claude_desktop.FILE
    assert not f.exists()
    claude_desktop.install()
    first = f.read_text()
    assert "already set up" in claude_desktop.install()[0] and f.read_text() == first


def test_desktop_refuses_broken_config_and_missing_app(sandbox, monkeypatch):
    f = sandbox / "desktop" / "Claude" / claude_desktop.FILE
    f.write_text("[1, 2")
    with pytest.raises(ConfigError):
        claude_desktop.install()
    assert f.read_text() == "[1, 2"
    monkeypatch.setenv("SUPERCHAT_CLAUDE_DESKTOP_DIR", str(sandbox / "nowhere"))
    assert not claude_desktop.detected()
    monkeypatch.setattr(claude_desktop.sys, "platform", "linux")
    monkeypatch.delenv("SUPERCHAT_CLAUDE_DESKTOP_DIR")
    with pytest.raises(ConfigError, match="does not seem to be installed"):
        claude_desktop.install()


def test_desktop_writes_to_every_existing_claude_folder(sandbox, monkeypatch):
    """Microsoft Store build and classic installer folders can both exist; cover both."""
    a, b = sandbox / "a" / "Claude", sandbox / "b" / "Claude"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    monkeypatch.setattr(claude_desktop, "config_dirs", lambda: [a, b])
    assert len(claude_desktop.install()) == 2
    assert (a / claude_desktop.FILE).exists() and (b / claude_desktop.FILE).exists()
    assert len(claude_desktop.uninstall()) == 2
    assert "superchat" not in json.loads((a / claude_desktop.FILE).read_text())["mcpServers"]


# ---- CLI setup ---------------------------------------------------------------------------------------------

def test_cli_setup_and_uninstall_end_to_end(sandbox, capsys):
    assert cli.main(["setup", "--agents", "claude-desktop", "--key", "pub-key-123"]) == 0
    out = capsys.readouterr().out
    assert "the team default" in out and "Publishable key: set" in out and "superchat login --email" in out
    assert config.load().supabase_key == "pub-key-123"
    assert cli.main(["uninstall"]) == 0
    assert claude_desktop.status() == [(str(sandbox / "desktop" / "Claude" / claude_desktop.FILE), False)]


def test_cli_setup_rejects_unknown_agent(sandbox, capsys):
    assert cli.main(["setup", "--agents", "notepad"]) == 2
    assert "unknown agent" in capsys.readouterr().err


# ---- hooks and strict mode -----------------------------------------------------------------------------------

def test_session_start_tells_claude_the_chat_id_and_folder():
    out = hooks.handle("session-start", {"session_id": "abc-123", "cwd": "C:/work/billing"})
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SessionStart"
    assert "superchat chat id: abc-123" in ctx["additionalContext"] and "superchat folder: C:/work/billing" in ctx["additionalContext"]


def test_strict_switches_on_only_for_that_session():
    assert not hooks.is_strict("s1")
    out = hooks.handle("user-prompt", {"session_id": "s1", "prompt": "/strict"})
    assert "Strict mode is now ON" in out["hookSpecificOutput"]["additionalContext"]
    assert hooks.is_strict("s1") and not hooks.is_strict("s2")


@pytest.mark.parametrize("tool", ["match", "brief", "search", "resolve_context", "companies"])
def test_strict_blocks_every_knowledge_read(tool):
    hooks.strict_on("s1")
    out = hooks.handle("pre-tool-use", {"session_id": "s1", "tool_name": f"mcp__superchat__{tool}"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hooks.handle("pre-tool-use", {"session_id": "other", "tool_name": f"mcp__superchat__{tool}"}) is None


@pytest.mark.parametrize("tool", ["keep", "chat_contributions", "chat_tag", "review_list", "push_review", "login", "whoami"])
def test_strict_never_blocks_keeping_or_reviewing(tool):
    hooks.strict_on("s1")
    assert hooks.handle("pre-tool-use", {"session_id": "s1", "tool_name": f"mcp__superchat__{tool}"}) is None


def test_strict_ignores_other_servers_tools_and_other_prompts():
    hooks.strict_on("s1")
    assert hooks.handle("pre-tool-use", {"session_id": "s1", "tool_name": "mcp__github__search"}) is None
    assert hooks.handle("pre-tool-use", {"session_id": "s1", "tool_name": "Bash"}) is None
    assert hooks.handle("user-prompt", {"session_id": "s9", "prompt": "please be strict about tests"}) is None
    assert not hooks.is_strict("s9")


def test_strict_session_survives_a_restart_and_can_be_switched_off():
    hooks.strict_on("s1")
    start = hooks.handle("session-start", {"session_id": "s1", "cwd": "x"})["hookSpecificOutput"]["additionalContext"]
    assert "Strict mode is ON" in start
    hooks.strict_off("s1")
    assert not hooks.is_strict("s1")


def test_hostile_session_id_cannot_escape_the_strict_folder():
    hooks.strict_on("../../evil")
    assert hooks.marker("../../evil").parent == hooks.paths.strict_dir()
    assert hooks.is_strict("../../evil")


def test_hook_never_breaks_the_session_on_bad_input(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert hooks.run("session-start") == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert hooks.run("pre-tool-use") == 0
    assert capsys.readouterr().out.count("hookSpecificOutput") <= 1


def test_hook_runs_as_a_real_subprocess(sandbox):
    env = {"SUPERCHAT_HOME": str(sandbox / "sc"), "PATH": ""}
    r = subprocess.run([sys.executable, "-m", "superchat", "hook", "session-start"], input=json.dumps(
        {"session_id": "sub-1", "cwd": "/w"}), capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "superchat chat id: sub-1" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


# ---- reminder ---------------------------------------------------------------------------------------------------

S = config.Settings()
WEEKDAY_4PM = datetime(2026, 11, 25, 16, 0)     # a Wednesday
SATURDAY_4PM = datetime(2026, 11, 28, 16, 0)


def kept(n=1):
    queue.add([{"title": f"t{i}", "decision": f"decision number {i}"} for i in range(n)], chat_id="c")


@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 11, 25, 15, 0), True), (datetime(2026, 11, 25, 17, 59), True),
    (datetime(2026, 11, 25, 14, 59), False), (datetime(2026, 11, 25, 18, 0), False),
    (datetime(2026, 11, 28, 16, 0), False), (datetime(2026, 11, 29, 16, 0), False),   # Saturday, Sunday
    (datetime(2026, 11, 27, 16, 30), True),                                           # Friday
])
def test_reminder_window_is_weekdays_3_to_6pm(when, expected):
    assert reminder.in_window(when, S) is expected


def test_reminder_needs_something_waiting():
    assert reminder.message(WEEKDAY_4PM, S) is None
    kept(2)
    assert "2 kept decisions waiting" in reminder.message(WEEKDAY_4PM, S)


def test_reminder_is_shown_at_most_once_an_hour():
    kept()
    assert reminder.message(WEEKDAY_4PM, S, clock=lambda: 10000.0)
    assert reminder.message(WEEKDAY_4PM, S, clock=lambda: 10000.0 + 3599) is None
    assert reminder.message(WEEKDAY_4PM, S, clock=lambda: 10000.0 + 3601)


def test_reminder_counts_cached_desktop_drafts_and_stays_quiet_outside_hours():
    state.set_(draft_count=3)
    assert "3 kept decisions" in reminder.message(WEEKDAY_4PM, S)
    state.set_(last_reminder=0)
    assert reminder.message(SATURDAY_4PM, S) is None


def test_reminder_reaches_the_user_through_the_hooks(monkeypatch):
    kept()
    out = hooks.handle("user-prompt", {"session_id": "s", "prompt": "hello"}, now=WEEKDAY_4PM)
    assert "waiting for review" in out["hookSpecificOutput"]["additionalContext"]
    assert hooks.handle("user-prompt", {"session_id": "s", "prompt": "again"}, now=WEEKDAY_4PM) is None   # throttled


def test_sandbox_mode_never_runs_the_real_claude_command(sandbox, monkeypatch):
    """Regression: a test run once registered a server in the developer's real Claude Code."""
    ran = []
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(claude_code.subprocess, "run", lambda *a, **k: ran.append(a) or (_ for _ in ()).throw(AssertionError("ran claude")))
    assert "skipped" in claude_code.register_mcp()
    claude_code.uninstall()
    assert ran == []
