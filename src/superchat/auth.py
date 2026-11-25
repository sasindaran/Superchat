"""
Email-code sign-in against Supabase Auth.

    request_code(email)      -> Supabase emails a 6-digit code (nobody needs a password)
    verify_code(email, code) -> session saved once per machine, shared by every agent on it

Only the publishable key and the person's own session are ever used.
"""
import http.server
import json
import secrets
import socket
import threading
import time
import urllib.parse

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


def request_code(settings: Settings, email: str, client=None, redirect_to: str | None = None) -> None:
    if not settings.configured:
        raise AuthError("Supabase URL / publishable key are not configured (run `superchat setup`).")
    email = email.strip().lower()
    url = f"{settings.supabase_url}/auth/v1/otp" + (f"?redirect_to={urllib.parse.quote(redirect_to, safe='')}" if redirect_to else "")
    r = _client(client).post(url, headers=_headers(settings), json={"email": email, "create_user": False})
    if r.status_code >= 400:
        msg = _message(r)
        if r.status_code == 429:
            raise AuthError("Too many sign-in emails requested. Wait a minute and try again.")
        if "signup" in msg.lower() or "not allowed" in msg.lower() or r.status_code == 422:
            raise AuthError(f"This email has not been invited to the team's Supabase ({msg}). Ask the owner to add you.")
        raise AuthError(f"Could not send the code: {msg}")


# ---- link sign-in (works with Supabase's built-in email, which only sends a link) ----------------------------
# `superchat login` asks Supabase to email a link whose return address is a tiny page on THIS computer
# (127.0.0.1). Clicking the link in a browser on this computer hands the session back to us.
# A just-used port can stay reserved for a minute or two on Windows, so there are plenty to choose from.
LOOPBACK_PORTS = tuple(range(53682, 53702))               # all of these must be in Supabase's redirect allow-list
ALLOW_LIST = [f"http://127.0.0.1:{p}/**" for p in LOOPBACK_PORTS]

PAGE = r"""<!doctype html><meta charset="utf-8"><title>Superchat sign-in</title>
<body style="font:16px system-ui,sans-serif;max-width:34rem;margin:4rem auto;padding:0 1rem">
<h2 id="h">Signing you in...</h2><p id="p"></p>
<script>
var f = new URLSearchParams(location.hash.slice(1)), q = new URLSearchParams(location.search);
var err = f.get('error_description') || q.get('error_description');
function say(t, m) { document.getElementById('h').textContent = t; document.getElementById('p').textContent = m; }
function post(body, ok) {
  fetch('', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body})
    .then(function (r) { r.ok ? say(ok[0], ok[1]) : say('Sign-in failed', 'Superchat did not accept this link. Ask for a new one.'); })
    .catch(function () { say('Sign-in failed', 'Could not reach Superchat on this computer.'); });
}
if (err) { say('Sign-in failed', err.replace(/\+/g, ' ')); post('error=' + encodeURIComponent(err), ['', '']); }
else if (f.get('access_token')) { post(f.toString(), ['Signed in to Superchat', 'You can close this tab and go back to Claude.']); }
else { say('Nothing to do', 'Open the link from your Superchat sign-in email on this computer.'); }
history.replaceState(null, '', location.pathname);
</script>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "superchat"

    def log_message(self, *a):          # keep the terminal quiet
        pass

    def _ok(self) -> bool:
        return self.path.split("?", 1)[0] == f"/cb/{self.server.nonce}"

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._ok():
            return self._send(404, b"not found")
        self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16384:
            return self._send(413, b"too large")
        raw = self.rfile.read(n).decode("utf-8", "replace")      # always read the body first, or Windows resets the connection
        if not self._ok():
            return self._send(404, b"not found")
        if self.server.done.is_set():
            return self._send(409, b"already used")
        fields = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        if fields.get("error"):
            self.server.error = fields["error"]
        elif fields.get("access_token") and fields.get("refresh_token"):
            self.server.tokens = fields
        else:
            return self._send(400, b"incomplete")
        self.server.done.set()
        self._send(200, b"ok")


class _Server(http.server.ThreadingHTTPServer):
    # The default (SO_REUSEADDR) lets two listeners share a port on Windows, which would misroute a sign-in link.
    allow_reuse_address = False
    daemon_threads = True


class LinkLogin:
    """A one-shot listener on 127.0.0.1 waiting for the sign-in link to be clicked."""

    def __init__(self, ports=LOOPBACK_PORTS, nonce: str | None = None):
        self.nonce = nonce or secrets.token_urlsafe(16)
        self.server = None
        for port in ports:
            try:
                self.server = _Server(("127.0.0.1", port), _Handler)
                break
            except OSError:
                continue
        if self.server is None:
            raise AuthError("Another sign-in is already waiting on this computer (ports "
                            f"{ports[0]}-{ports[-1]} are busy). Finish or wait for it, then try again.")
        self.port = self.server.server_address[1]
        self.server.nonce, self.server.done, self.server.tokens, self.server.error = self.nonce, threading.Event(), None, None
        threading.Thread(target=self.server.serve_forever, daemon=True, name="superchat-login").start()

    @property
    def redirect_to(self) -> str:
        return f"http://127.0.0.1:{self.port}/cb/{self.nonce}"

    def wait(self, settings: Settings, timeout: float = 600, client=None) -> dict:
        try:
            if not self.server.done.wait(timeout):
                raise AuthError("Timed out waiting for the sign-in link to be clicked. Run login again for a new link.")
            if self.server.error:
                raise AuthError("Sign-in failed: " + self.server.error.replace("+", " "))
            tokens = dict(self.server.tokens)
            user = _client(client).get(f"{settings.supabase_url}/auth/v1/user", headers={
                "apikey": settings.supabase_key, "Authorization": f"Bearer {tokens['access_token']}"})
            if user.status_code >= 400:
                raise AuthError(f"Signed in, but could not read your profile: {_message(user)}")
            tokens["user"] = user.json()
            tokens.setdefault("expires_in", "3600")
            return _save(tokens)
        finally:
            self.close()

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def start_link_login(settings: Settings, email: str, client=None, ports=LOOPBACK_PORTS) -> LinkLogin:
    """Open the local listener and have Supabase email the sign-in link. Call .wait() on the result."""
    ll = LinkLogin(ports)
    try:
        request_code(settings, email, client=client, redirect_to=ll.redirect_to)
    except Exception:
        ll.close()
        raise
    return ll


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
