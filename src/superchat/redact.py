"""Mask anything that looks like a secret before text is stored or shared."""
import re

_RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("db-url-password", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):([^\s@/]+)@")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("supabase-key", re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_\-]{10,}\b")),
    ("api-key", re.compile(r"\b(?:sk|pk|rk|gsk|jina)[-_][A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}")),
    ("secret-assignment", re.compile(
        r"(?i)\b([A-Za-z0-9_.\-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[A-Za-z0-9_.\-]*)"
        r"(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})\3")),
]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    out = text
    for name, rx in _RULES:
        if name == "db-url-password":
            out = rx.sub(lambda m: f"{m.group(1)}:[REDACTED]@", out)
        elif name == "secret-assignment":
            out = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = rx.sub(f"[REDACTED:{name}]", out)
    return out
