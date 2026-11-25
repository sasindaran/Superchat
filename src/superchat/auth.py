"""
Email-code sign-in against Supabase Auth.

    request_code(email)      -> Supabase emails a 6-digit code (nobody needs a password)
    verify_code(email, code) -> session saved once per machine, shared by every agent on it

Only the publishable key and the person's own session are ever used.
"""
import json
import time

import httpx

from . import paths
from .config import Settings


class AuthError(Exception):
    pass


class NotSignedIn(AuthError):
    pass


def _headers(settings: Settings) -> dict:
    return {"apikey": settings.supabase_key, "Content-Type": "application/json"}


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
        return j.get("msg") or j.get("error_description") or j.get("message") or j.get("error") or r.text[:200]
    except ValueError:
        return r.text[:200]


def _client(client):
    return client or httpx.Client(timeout=30)


def request_code(settings: Settings, email: str, client=None) -> None:
    if not settings.configured:
        raise AuthError("Supabase URL / publishable key are not configured (run `superchat setup`).")
    email = email.strip().lower()
    r = _client(client).post(f"{settings.supabase_url}/auth/v1/otp", headers=_headers(settings),
                             json={"email": email, "create_user": False})
    if r.status_code >= 400:
        msg = _message(r)
        if r.status_code == 429:
            raise AuthError("Too many sign-in emails requested. Wait a minute and try again.")
        if "signup" in msg.lower() or "not allowed" in msg.lower() or r.status_code == 422:
            raise AuthError(f"This email has not been invited to the team's Supabase ({msg}). Ask the owner to add you.")
        raise AuthError(f"Could not send the code: {msg}")


def verify_code(settings: Settings, email: str, code: str, client=None) -> dict:
    email, code = email.strip().lower(), code.strip().replace(" ", "")
    c = _client(client)
    last = ""
    for kind in ("email", "magiclink"):  # newer / older Supabase wording for the same thing
        r = c.post(f"{settings.supabase_url}/auth/v1/verify", headers=_headers(settings),
                   json={"type": kind, "email": email, "token": code})
        if r.status_code < 400:
            return _save(r.json())
        last = _message(r)
    raise AuthError(f"That code was not accepted ({last}). Codes expire quickly; request a new one.")


def _save(tokens: dict) -> dict:
    user = tokens.get("user") or {}
    session = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": tokens.get("expires_at") or int(time.time()) + int(tokens.get("expires_in", 3600)),
        "user": {"id": user.get("id"), "email": user.get("email")},
    }
    paths.write_private(paths.session_file(), json.dumps(session))
    return session


def load_session() -> dict | None:
    f = paths.session_file()
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def access_token(settings: Settings, client=None) -> str:
    """A valid access token, refreshing it if it is about to expire."""
    s = load_session()
    if not s:
        raise NotSignedIn("Not signed in. Ask for a code with the `login` tool, then `verify_code`.")
    if s["expires_at"] - time.time() > 60:
        return s["access_token"]
    r = _client(client).post(f"{settings.supabase_url}/auth/v1/token?grant_type=refresh_token",
                             headers=_headers(settings), json={"refresh_token": s["refresh_token"]})
    if r.status_code >= 400:
        logout()
        raise NotSignedIn("Your session expired. Sign in again with a new code.")
    return _save(r.json())["access_token"]


def whoami() -> dict | None:
    s = load_session()
    return s["user"] if s else None


def logout() -> None:
    f = paths.session_file()
    if f.exists():
        f.unlink()
