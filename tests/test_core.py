"""Unit tests for config, secrets masking, the local queue, sign-in and folder identity."""
import json
import time

import httpx
import pytest

from superchat import auth, config, paths, state
from superchat.capture import folders, queue
from superchat.redact import redact


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own empty Superchat folder."""
    monkeypatch.setenv("SUPERCHAT_HOME", str(tmp_path / "sc"))
    for k in list(config.ENV_MAP) + ["SUPERCHAT_HOME_X"]:
        if k != "SUPERCHAT_HOME":
            monkeypatch.delenv(k, raising=False)
    return tmp_path / "sc"


# ---- settings --------------------------------------------------------------------------------

def test_defaults_come_from_the_package():
    s = config.load()
    assert s.supabase_url.startswith("https://") and s.embedding_dim == 384 and s.capture_mode == "auto"


def test_precedence_env_over_user_file_over_defaults(monkeypatch):
    assert config.load().supabase_url.endswith(".supabase.co")
    config.save_user(supabase_url="https://mine.supabase.co/", supabase_key="k1")
    s = config.load()
    assert (s.supabase_url, s.supabase_key) == ("https://mine.supabase.co", "k1")   # trailing slash trimmed
    monkeypatch.setenv("SUPERCHAT_SUPABASE_URL", "https://env.supabase.co")
    assert config.load().supabase_url == "https://env.supabase.co"
    assert config.load().supabase_key == "k1"


def test_unset_user_value_falls_back_to_default():
    config.save_user(supabase_url="https://mine.supabase.co")
    config.unset_user("supabase_url")
    assert config.load().supabase_url == config._packaged()["supabase_url"]


def test_configured_needs_url_and_key():
    assert not config.Settings(supabase_url="https://x", supabase_key="").configured
    assert config.Settings(supabase_url="https://x", supabase_key="k").configured


# ---- redaction -------------------------------------------------------------------------------

@pytest.mark.parametrize("secret", [
    "sb_secret_abcdefghij1234567890",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "sk-abcdefghijklmnopqrstuvwxyz",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
    "xoxb-1234567890-abcdefghij",
])
def test_known_token_shapes_are_masked(secret):
    out = redact(f"we used {secret} for that")
    assert secret not in out and "[REDACTED" in out


def test_connection_string_password_and_assignments_are_masked():
    out = redact("postgresql://postgres.abc:Sup3rS3cret!@db.example.com:5432/postgres")
    assert "Sup3rS3cret" not in out and "postgres.abc" in out and "@db.example.com" in out
    for text in ("password = hunter2hunter2", "API_KEY: abc123def456", 'token="zzzzzzzz9999"'):
        assert "REDACTED" in redact(text)


def test_ordinary_text_is_untouched():
    text = "We retry failed card payments three times, then email the client. Ticket ACME-1234."
    assert redact(text) == text
    assert redact(None) is None and redact("") == ""


# ---- local queue ------------------------------------------------------------------------------

def item(title="Retry payments", decision="Retry three times then email", **kw):
    return {"title": title, "decision": decision, **kw}


def test_queue_adds_fills_defaults_and_masks_secrets():
    r = queue.add([item(reason="key is sb_secret_abcdefghij1234567890")], chat_id="c1", source_agent="claude-code")
    assert r["waiting"] == 1
    saved = queue.read_all()[0]
    assert saved["chat_id"] == "c1" and saved["kind"] == "decision" and saved["keep_id"] and saved["kept_at"]
    assert "sb_secret" not in saved["reason"]


def test_queue_skips_repeats_in_the_same_chat_but_not_other_chats():
    queue.add([item()], chat_id="c1")
    again = queue.add([item(decision="  RETRY three times, then email!! ")], chat_id="c1")
    assert again["added"] == [] and again["skipped"] == ["Retry payments"] and queue.count() == 1
    other = queue.add([item()], chat_id="c2")
    assert len(other["added"]) == 1 and queue.count() == 2


def test_queue_rejects_incomplete_or_wrong_kind():
    with pytest.raises(ValueError):
        queue.add([{"title": "no decision"}])
    with pytest.raises(ValueError):
        queue.add([item(kind="rumour")])


def test_queue_for_chat_remove_and_torn_lines():
    queue.add([item("a", "alpha")], chat_id="c1")
    queue.add([item("b", "beta")], chat_id="c2")
    assert [i["title"] for i in queue.for_chat("c1")] == ["a"]
    with open(paths.queue_file(), "a", encoding="utf-8") as f:
        f.write('{"broken json\n')
    assert queue.count() == 2                                   # torn line ignored, nothing lost
    gone = queue.remove([queue.for_chat("c1")[0]["keep_id"]])
    assert gone == 1 and [i["title"] for i in queue.read_all()] == ["b"]


# ---- sign-in (faked Supabase) -----------------------------------------------------------------

SETTINGS = config.Settings(supabase_url="https://p.supabase.co", supabase_key="pub-key")


def fake(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def tokens(expires_in=3600, **kw):
    return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": expires_in,
            "user": {"id": "u-1", "email": "a@x.test"}, **kw}


def test_request_code_sends_email_without_creating_users():
    seen = {}

    def handler(req):
        seen["url"], seen["body"], seen["key"] = str(req.url), json.loads(req.content), req.headers["apikey"]
        return httpx.Response(200, json={})
    auth.request_code(SETTINGS, "  A@X.test ", client=fake(handler))
    assert seen["url"].endswith("/auth/v1/otp") and seen["key"] == "pub-key"
    assert seen["body"] == {"email": "a@x.test", "create_user": False}


@pytest.mark.parametrize("status,body,fragment", [
    (422, {"msg": "Signups not allowed for otp"}, "not been invited"),
    (429, {"msg": "rate limit"}, "Too many"),
    (500, {"msg": "boom"}, "boom"),
])
def test_request_code_errors_are_explained(status, body, fragment):
    with pytest.raises(auth.AuthError, match=fragment):
        auth.request_code(SETTINGS, "a@x.test", client=fake(lambda r: httpx.Response(status, json=body)))


def test_request_code_needs_configuration():
    with pytest.raises(auth.AuthError, match="not configured"):
        auth.request_code(config.Settings(), "a@x.test")


def test_verify_saves_session_and_whoami():
    def handler(req):
        body = json.loads(req.content)
        assert body == {"type": "email", "email": "a@x.test", "token": "123456"}
        return httpx.Response(200, json=tokens())
    auth.verify_code(SETTINGS, "a@x.test", "123 456", client=fake(handler))
    assert auth.whoami() == {"id": "u-1", "email": "a@x.test"}
    assert auth.access_token(SETTINGS, client=fake(lambda r: pytest.fail("should not refresh"))) == "access-1"


def test_verify_falls_back_to_magiclink_type_then_fails_clearly():
    calls = []

    def handler(req):
        t = json.loads(req.content)["type"]
        calls.append(t)
        return httpx.Response(200, json=tokens()) if t == "magiclink" else httpx.Response(403, json={"msg": "bad"})
    auth.verify_code(SETTINGS, "a@x.test", "111111", client=fake(handler))
    assert calls == ["email", "magiclink"]
    with pytest.raises(auth.AuthError, match="not accepted"):
        auth.verify_code(SETTINGS, "a@x.test", "1", client=fake(lambda r: httpx.Response(403, json={"msg": "expired"})))


def test_token_is_refreshed_when_close_to_expiry():
    auth.verify_code(SETTINGS, "a@x.test", "1", client=fake(lambda r: httpx.Response(200, json=tokens(expires_in=10))))

    def handler(req):
        assert "grant_type=refresh_token" in str(req.url) and json.loads(req.content) == {"refresh_token": "refresh-1"}
        return httpx.Response(200, json={**tokens(), "access_token": "access-2", "refresh_token": "refresh-2"})
    assert auth.access_token(SETTINGS, client=fake(handler)) == "access-2"
    assert auth.load_session()["refresh_token"] == "refresh-2"


def test_failed_refresh_signs_out():
    auth.verify_code(SETTINGS, "a@x.test", "1", client=fake(lambda r: httpx.Response(200, json=tokens(expires_in=10))))
    with pytest.raises(auth.NotSignedIn, match="expired"):
        auth.access_token(SETTINGS, client=fake(lambda r: httpx.Response(400, json={"msg": "revoked"})))
    assert auth.load_session() is None


def test_not_signed_in_and_logout():
    with pytest.raises(auth.NotSignedIn):
        auth.access_token(SETTINGS)
    auth.verify_code(SETTINGS, "a@x.test", "1", client=fake(lambda r: httpx.Response(200, json=tokens())))
    auth.logout()
    assert auth.whoami() is None


def test_session_file_is_written_atomically_and_readable():
    auth.verify_code(SETTINGS, "a@x.test", "1", client=fake(lambda r: httpx.Response(200, json=tokens())))
    assert json.loads(paths.session_file().read_text())["access_token"] == "access-1"
    assert not list(paths.home().glob("*.tmp"))


# ---- state and folders -------------------------------------------------------------------------

def test_device_id_is_stable():
    first = state.device_id()
    assert first.startswith("dev-") and state.device_id() == first


@pytest.mark.parametrize("remote,expected", [
    ("https://github.com/Acme/Billing.git", "github.com/acme/billing"),
    ("git@github.com:Acme/Billing.git", "github.com/acme/billing"),
    ("ssh://git@github.com/acme/billing", "github.com/acme/billing"),
    ("https://user:token123@github.com/acme/billing/", "github.com/acme/billing"),
    ("git@gitlab.example.com:group/sub/repo.git", "gitlab.example.com/group/sub/repo"),
])
def test_git_remotes_normalise_to_one_key(remote, expected):
    assert folders.normalize_remote(remote) == expected


def test_folder_key_uses_git_remote_else_local_hash(tmp_path):
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    plain = folders.folder_key(str(repo))
    assert plain.startswith("local:")
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:Acme/Billing.git"], check=True)
    assert folders.folder_key(str(repo)) == "github.com/acme/billing"
    assert folders.folder_key(None) is None
