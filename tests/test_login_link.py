"""Link sign-in: the emailed link returns to a one-shot listener on 127.0.0.1 and hands the session to Superchat."""
import http.server
import json
import threading
import time
import urllib.parse

import httpx
import pytest

from superchat import auth, cli, config

FRAGMENT = urllib.parse.urlencode({"access_token": "acc-1", "refresh_token": "ref-1", "expires_in": "3600",
                                   "token_type": "bearer"})


_next = [56000 + (int(time.time()) % 500) * 20]


@pytest.fixture()
def ports(monkeypatch):
    """Fresh, unused ports for each test (a just-used port can stay reserved for a while on Windows)."""
    chosen = tuple(range(_next[0], _next[0] + 6))
    _next[0] += 6
    monkeypatch.setattr(auth, "LOOPBACK_PORTS", chosen)
    return chosen


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERCHAT_HOME", str(tmp_path / "sc"))
    for k in config.ENV_MAP:
        if k != "SUPERCHAT_HOME":
            monkeypatch.delenv(k, raising=False)


class FakeSupabase:
    """Just enough of Supabase Auth: records the email request, answers /user."""

    def __init__(self):
        self.otp_requests, outer = [], self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path.startswith("/auth/v1/otp"):
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    outer.otp_requests.append({"redirect_to": (q.get("redirect_to") or [None])[0], "body": body,
                                               "apikey": self.headers.get("apikey")})
                    return self._json(200, {})
                self._json(404, {})

            def do_GET(self):
                if self.path == "/auth/v1/user" and self.headers.get("Authorization") == "Bearer acc-1":
                    return self._json(200, {"id": "u-1", "email": "a@x.test"})
                self._json(401, {"msg": "bad token"})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def supa(monkeypatch):
    s = FakeSupabase()
    monkeypatch.setenv("SUPERCHAT_SUPABASE_URL", s.url)
    monkeypatch.setenv("SUPERCHAT_SUPABASE_KEY", "pub-key")
    yield s
    s.stop()


def browser_click(redirect_to, fragment=FRAGMENT):
    """What the person's browser does after clicking the emailed link."""
    page = httpx.get(redirect_to, timeout=10)
    assert page.status_code == 200 and "location.hash" in page.text
    return httpx.post(redirect_to, content=fragment, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)


def in_thread(fn):
    out = {}

    def run():
        try:
            out["result"] = fn()
        except Exception as e:
            out["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def test_allow_list_covers_every_port_we_may_use():
    assert len(auth.LOOPBACK_PORTS) >= 20 and auth.ALLOW_LIST == [f"http://127.0.0.1:{p}/**" for p in auth.LOOPBACK_PORTS]


def test_link_login_sends_the_email_with_a_local_return_address_and_saves_the_session(supa, ports):
    s = config.load()
    ll = auth.start_link_login(s, " A@X.test ", ports=ports)
    req = supa.otp_requests[0]
    assert req["body"] == {"email": "a@x.test", "create_user": False} and req["apikey"] == "pub-key"
    assert req["redirect_to"] == ll.redirect_to and ll.redirect_to.startswith("http://127.0.0.1:")
    assert ll.server.server_address[0] == "127.0.0.1"                       # never reachable from other machines

    t, out = in_thread(lambda: ll.wait(s, 15))
    assert browser_click(ll.redirect_to).status_code == 200
    t.join(10)
    assert out["result"]["user"] == {"id": "u-1", "email": "a@x.test"}
    assert auth.whoami() == {"id": "u-1", "email": "a@x.test"}
    assert auth.access_token(s, client=httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("refreshed")))) == "acc-1"


def test_only_the_exact_secret_path_is_served_and_only_once(supa, ports):
    s = config.load()
    ll = auth.start_link_login(s, "a@x.test", ports=ports)
    base = ll.redirect_to.rsplit("/cb/", 1)[0]
    assert httpx.get(base + "/cb/wrong-nonce").status_code == 404
    assert httpx.get(base + "/").status_code == 404
    assert httpx.post(base + "/cb/wrong-nonce", content=FRAGMENT).status_code == 404
    assert httpx.post(ll.redirect_to, content="access_token=only-half").status_code == 400
    t, out = in_thread(lambda: ll.wait(s, 15))
    assert browser_click(ll.redirect_to).status_code == 200
    t.join(10)
    assert "result" in out


def test_an_error_in_the_link_is_reported_not_hidden(supa, ports):
    s = config.load()
    ll = auth.start_link_login(s, "a@x.test", ports=ports)
    t, out = in_thread(lambda: ll.wait(s, 15))
    httpx.post(ll.redirect_to, content="error=Email+link+is+invalid+or+has+expired")
    t.join(10)
    assert isinstance(out["error"], auth.AuthError) and "invalid or has expired" in str(out["error"])
    assert auth.whoami() is None


def test_timeout_is_clear_and_frees_the_port(supa, ports):
    s = config.load()
    ll = auth.start_link_login(s, "a@x.test", ports=ports)
    port = ll.port
    with pytest.raises(auth.AuthError, match="Timed out"):
        ll.wait(s, 0.2)
    again = auth.LinkLogin((port,))                                          # the same port can be used again
    again.close()


def test_a_token_that_supabase_rejects_does_not_sign_you_in(supa, ports):
    s = config.load()
    ll = auth.start_link_login(s, "a@x.test", ports=ports)
    t, out = in_thread(lambda: ll.wait(s, 15))
    browser_click(ll.redirect_to, urllib.parse.urlencode({"access_token": "forged", "refresh_token": "r"}))
    t.join(10)
    assert isinstance(out["error"], auth.AuthError) and "could not read your profile" in str(out["error"])
    assert auth.whoami() is None


def test_busy_ports_fall_back_then_fail_clearly(ports):
    first = auth.LinkLogin(ports)
    second = auth.LinkLogin(ports)
    assert second.port != first.port                                         # never two listeners on one port
    taken = [auth.LinkLogin((p,)) for p in ports if p not in (first.port, second.port)]
    with pytest.raises(auth.AuthError, match="already waiting"):
        auth.LinkLogin(ports)
    for ll in [first, second, *taken]:
        ll.close()


def test_failed_email_request_closes_the_listener(supa, ports, monkeypatch):
    s = config.load()
    monkeypatch.setattr(auth, "request_code", lambda *a, **k: (_ for _ in ()).throw(auth.AuthError("not invited")))
    with pytest.raises(auth.AuthError, match="not invited"):
        auth.start_link_login(s, "a@x.test", ports=ports)
    ll = auth.LinkLogin((ports[0],))                                          # nothing is left holding the first port
    ll.close()


def test_not_invited_email_is_explained(supa, monkeypatch):
    s = config.load()
    transport = httpx.MockTransport(lambda r: httpx.Response(422, json={"msg": "Signups not allowed for otp"}))
    with pytest.raises(auth.AuthError, match="not been invited"):
        auth.start_link_login(s, "stranger@x.test", client=httpx.Client(transport=transport))


def test_background_login_end_to_end_with_a_real_detached_process(supa, ports, tmp_path):
    """`superchat login` returns at once; a detached process finishes the sign-in when the link is clicked."""
    s = config.load()
    t0 = time.time()
    cli.login_in_background(s, "a@x.test", wait=60)
    assert time.time() - t0 < 20                                              # returned without waiting for the click
    redirect = supa.otp_requests[0]["redirect_to"]
    assert redirect.startswith("http://127.0.0.1:")
    assert auth.whoami() is None                                              # not signed in until the link is clicked
    assert browser_click(redirect).status_code == 200
    for _ in range(100):
        if auth.whoami():
            break
        time.sleep(0.1)
    assert auth.whoami() == {"id": "u-1", "email": "a@x.test"}
    with pytest.raises(httpx.ConnectError):                                   # the listener is one-shot: gone now
        httpx.post(redirect, content=FRAGMENT)


def test_existing_session_with_string_expiry_is_accepted(supa):
    session = {"access_token": "access", "refresh_token": "refresh",
               "expires_at": str(int(time.time()) + 3600), "user": {}}
    auth.paths.write_private(auth.paths.session_file(), json.dumps(session))
    assert auth.access_token(config.load()) == "access"
