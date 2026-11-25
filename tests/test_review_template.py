"""Runs tests/review_template_check.js: the review screen driven in jsdom against a fake host:superchat MCP."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_review_screen_behaviour(tmp_path):
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        pytest.skip("node/npm not installed")
    install = subprocess.run([npm, "install", "--silent", "--no-audit", "--no-fund", "--prefix", str(tmp_path), "jsdom@24"],
                             capture_output=True, text=True, timeout=300, shell=(npm.lower().endswith(".cmd")))
    if install.returncode != 0:
        pytest.skip(f"could not install jsdom: {install.stderr[:200]}")
    run = subprocess.run([node, str(ROOT / "tests" / "review_template_check.js"), str(ROOT / "src" / "superchat" / "assets" / "review" / "template.html")],
                         capture_output=True, text=True, timeout=120, env={**os.environ, "NODE_PATH": str(tmp_path / "node_modules")})
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    assert "ALL " in run.stdout and "PASSED" in run.stdout
