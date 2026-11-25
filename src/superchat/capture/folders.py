"""Identify a project folder the same way on every machine (via its git remote)."""
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path


def normalize_remote(url: str) -> str:
    u = url.strip()
    u = re.sub(r"^[a-z+]+://", "", u, flags=re.I)   # https://, ssh://, git+ssh://
    u = re.sub(r"^[^@/]+@", "", u)                  # git@ or user:token@
    u = re.sub(r":(?!\d+/)", "/", u, count=1)       # host:org/repo -> host/org/repo
    u = re.sub(r"\.git/?$", "", u)
    return u.strip("/").lower()


def folder_key(path) -> str | None:
    if not path:
        return None
    p = Path(path).expanduser()
    try:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            result = subprocess.run(
                ["git", "-C", str(p), "config", "--get", "remote.origin.url"],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, timeout=5,
            )
            output.seek(0)
            remote = output.read().strip()
        if result.returncode == 0 and remote:
            return normalize_remote(remote)
    except (OSError, subprocess.SubprocessError):
        pass
    # not a git repo with a remote: a per-machine key (cannot be shared with teammates)
    return "local:" + hashlib.sha1(str(p.resolve()).lower().encode()).hexdigest()[:12]
