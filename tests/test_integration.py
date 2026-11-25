"""
End to end through the real client code: Api -> PostgREST (the same layer Supabase uses) -> the real schema,
with the real local embedding model. Skipped when docker is not available.
"""
import base64
import hashlib
import hmac
import json
import subprocess
import time
import uuid

import httpx
import psycopg
import pytest

from superchat import auth, config, mcp_server as server, paths, state
from superchat.capture import drafts, queue
from superchat.db import Api, ApiError
from superchat.review import build as review_build
from superchat.review import push as review_push
from superchat.review.push import PushRefused

SECRET = "test-secret-test-secret-test-secret-123456"
PORT = 3100
URL = f"http://localhost:{PORT}"
CONTAINER = "superchat-postgrest"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint(role="authenticated", sub=None, email=None, ttl=3600):
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = {"role": role, "aud": "authenticated", "exp": int(time.time()) + ttl}
    if sub:
        body.update(sub=str(sub), email=email)
    payload = b64(json.dumps(body).encode())
    sig = b64(hmac.new(SECRET.encode(), f"{head}.{payload}".encode(), hashlib.sha256).digest())
    return f"{head}.{payload}.{sig}"


@pytest.fixture(scope="session")
def postgrest(dsn):
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("docker is not running")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("do $$ begin if not exists (select from pg_roles where rolname='authenticator') then "
                  "create role authenticator login noinherit password 'authpw'; end if; end $$")
        c.execute("grant anon, authenticated to authenticator")
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    run = subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "-p", f"{PORT}:3000",
                          "-e", "PGRST_DB_URI=postgres://authenticator:authpw@host.docker.internal:5433/superchat_test",
                          "-e", "PGRST_DB_SCHEMAS=public", "-e", "PGRST_DB_ANON_ROLE=anon",
                          "-e", "PGRST_DB_EXTRA_SEARCH_PATH=public,extensions",
                          "-e", f"PGRST_JWT_SECRET={SECRET}", "postgrest/postgrest"], capture_output=True, text=True)
    if run.returncode != 0:
        pytest.skip(f"could not start PostgREST: {run.stderr[:200]}")
    for _ in range(40):
        try:
            if httpx.get(URL + "/", headers={"Authorization": f"Bearer {mint('anon')}"}, timeout=2).status_code < 500:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        logs = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True).stderr[-500:]
        pytest.fail(f"PostgREST did not start: {logs}")
    yield URL
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)


class StripRestPrefix(httpx.BaseTransport):
    """Supabase serves PostgREST under /rest/v1/; a standalone PostgREST serves it at the root."""
    def __init__(self):
        self.inner = httpx.HTTPTransport()

    def handle_request(self, request):
        path = request.url.raw_path.decode()
        if path.startswith("/rest/v1"):
            request.url = request.url.copy_with(raw_path=(path[len("/rest/v1"):] or "/").encode())
        return self.inner.handle_request(request)


@pytest.fixture()
def env(su, postgrest, tmp_path, monkeypatch):
    """A fresh Superchat home, settings pointing at PostgREST, and sign-in helpers."""
    import types
    from superchat import db as db_module
    shim = types.SimpleNamespace(**vars(httpx))          # only superchat.db sees the patched Client
    shim.Client = lambda **kw: httpx.Client(transport=StripRestPrefix(), **kw)
    monkeypatch.setattr(db_module, "httpx", shim)
    monkeypatch.setenv("SUPERCHAT_HOME", str(tmp_path / "sc"))
    monkeypatch.setenv("SUPERCHAT_SUPABASE_URL", postgrest)
    monkeypatch.setenv("SUPERCHAT_SUPABASE_KEY", mint("anon"))
    monkeypatch.delenv("SUPERCHAT_CAPTURE", raising=False)

    class Env:
        settings = config.load()

        @staticmethod
        def sign_in(person):
            paths.write_private(paths.session_file(), json.dumps({
                "access_token": mint(sub=person.id, email=person.email), "refresh_token": "r",
                "expires_at": int(time.time()) + 3000, "user": {"id": str(person.id), "email": person.email}}))

        @staticmethod
        def api():
            return Api(config.load())
    return Env


class FakeCtx:
    def __init__(self, client):
        self.session = type("S", (), {"client_params": type("P", (), {"clientInfo": type("I", (), {"name": client})()})()})()


def item(title, decision, **kw):
    return {"title": title, "decision": decision, "condition": kw.pop("condition", None),
            "reason": kw.pop("reason", None), **kw}


# ---- plumbing -----------------------------------------------------------------------------------------

def test_schema_version_is_readable_before_sign_in(env):
    assert env.api().schema_version() == "1"


def test_calls_need_a_session(env):
    with pytest.raises(auth.NotSignedIn):
        env.api().rpc("chat_contributions", {"p_chat_id": "x"})


def test_database_rules_are_enforced_through_the_client(env, alice, bob):
    env.sign_in(alice)
    with pytest.raises(ApiError):                                    # nobody can read admin_emails
        env.api().select("admin_emails")
    env.sign_in(bob)
    assert env.api().select("decisions") == []


# ---- capture ------------------------------------------------------------------------------------------

def test_desktop_keep_goes_to_private_drafts_and_code_keep_to_local_queue(env, alice, bob):
    env.sign_in(alice)
    r = server.keep([item("Use UTC", "Store timestamps in UTC")], chat_id="sc-1", folder=None, ctx=FakeCtx("claude-ai"))
    assert r["kept"] == 1 and r["stored_in"] == "private drafts in Supabase" and queue.count() == 0
    again = server.keep([item("Use UTC", "store timestamps in utc!")], chat_id="sc-1", ctx=FakeCtx("claude-ai"))
    assert again["kept"] == 0 and again["skipped_as_already_kept"] == ["Use UTC"]

    c = server.keep([item("Code decision", "Decided in code")], chat_id="cc-1", ctx=FakeCtx("claude-code"))
    assert c["stored_in"] == "this computer's queue" and queue.count() == 1

    env.sign_in(bob)
    assert env.api().select("decisions") == []                       # drafts are private


def test_desktop_keep_falls_back_to_local_queue_when_signed_out(env):
    r = server.keep([item("Offline", "Kept while signed out")], chat_id="c", ctx=FakeCtx("claude-ai"))
    assert r["stored_in"] == "this computer's queue" and "Not saved to Supabase" in r["note"]


def test_secrets_are_masked_before_storing(env, alice):
    env.sign_in(alice)
    server.keep([item("Deploy key", "Use the key", reason="password = hunter2hunter2")], chat_id="c", ctx=FakeCtx("claude-ai"))
    assert "hunter2" not in json.dumps(env.api().select("decisions"))


def test_chat_contributions_sees_queue_and_database(env, alice):
    env.sign_in(alice)
    server.keep([item("A", "alpha decision")], chat_id="chat-9", ctx=FakeCtx("claude-ai"))
    server.keep([item("B", "beta decision")], chat_id="chat-9", ctx=FakeCtx("claude-code"))
    out = server.chat_contributions("chat-9")
    assert [q["title"] for q in out["queued"]] == ["B"] and [d["title"] for d in out["in_database"]] == ["A"]


# ---- review and the single push -------------------------------------------------------------------------

def push_payload(lst, company="Acme", product="Billing", drop=()):
    return {"cutoff": lst["cutoff"],
            "items": [{**{k: i[k] for k in ("keep_id", "chat_id", "kind", "title", "decision", "condition", "reason",
                                              "original_text", "source_agent", "folder_key", "kept_at")},
                       "company": {"name": company}, "product": {"name": product} if product else None}
                      for i in lst["items"] if i["keep_id"] not in drop],
            "remove_keep_ids": list(drop)}


def test_full_cycle_keep_review_push_search(env, alice, bob):
    env.sign_in(alice)
    server.keep([item("Retry failed payments", "Retry a failed card payment three times, then email the client",
                      condition="the card is declined", reason="most declines are temporary"),
                 item("Invoice numbering", "Invoices are numbered sequentially per calendar year"),
                 item("Dropped idea", "Maybe use fax", reason="not needed")],
                chat_id="cc-1", ctx=FakeCtx("claude-code"))
    server.keep([item("Always UTC", "Store every timestamp in UTC")], chat_id="d-1", ctx=FakeCtx("claude-ai"))

    lst = server.review_list()
    assert len(lst["items"]) == 4 and lst["cutoff"] == lst["built_at"] and lst["companies"] == []
    assert {i["source"] for i in lst["items"]} == {"queue", "draft"}
    assert all(i["suggestion"]["strength"] == "none" for i in lst["items"])      # first time: nothing is known

    fax = next(i["keep_id"] for i in lst["items"] if i["title"] == "Dropped idea")
    items = push_payload(lst, drop=[fax])["items"]
    for it in items:
        if it["title"] == "Always UTC":
            it["product"] = None                      # no product = company-wide guideline
    res = server.push_review(**{"cutoff": lst["cutoff"], "remove_keep_ids": [fax], "items": items})
    assert res["saved"] == 3 and res["removed"] == 0 and res["embeddings"] == "stored"
    assert queue.count() == 0                                                     # local queue cleared
    assert state.get("last_cutoff") == lst["cutoff"]
    assert env.api().select("decisions", status="eq.unsaved") == []               # draft promoted, not duplicated
    assert len(env.api().select("decisions", status="eq.saved")) == 3

    # another employee reads it, scoped to the company; meaning search works without shared words
    env.sign_in(bob)
    cos = server.companies()
    assert [c["name"] for c in cos] == ["Acme"] and cos[0]["products"] == ["Billing"]
    found = server.search("how many times do we re-attempt declined credit cards", company="Acme", product="Billing")
    assert found["mode"] == "keyword+meaning"
    assert found["results"][0]["title"] == "Retry failed payments"
    assert found["results"][0]["company"] == "Acme" and found["results"][0]["product"] == "Billing"
    assert server.match("how often do we retry a declined card?", company="Acme")["strong"] is True
    assert server.match("what colour should the office walls be?", company="Acme")["strong"] is False
    brief = server.brief("Acme", "Billing")
    assert {d["title"] for d in brief["product_decisions"]} == {"Retry failed payments", "Invoice numbering"}
    assert [g["title"] for g in brief["guidelines"]] == ["Always UTC"]          # company-wide, applies to every product


def test_second_time_the_company_is_recognised_and_lookalikes_are_shown(env, alice):
    env.sign_in(alice)
    server.keep([item("Retry payments", "Retry a failed card payment three times then email the client")],
                chat_id="c1", ctx=FakeCtx("claude-code"))
    first = server.review_list()
    server.push_review(**push_payload(first, "Acme", "Billing"))

    server.keep([item("Payment retries", "Failed card payments are retried 3 times before we email the customer")],
                chat_id="c2", ctx=FakeCtx("claude-code"))
    server.keep([item("New thing for Acme Billing", "Acme Billing invoices go out on the 1st")], chat_id="c3",
                ctx=FakeCtx("claude-code"))
    server.keep([item("Unrelated", "Standup moves to 10am")], chat_id="c4", ctx=FakeCtx("claude-code"))
    lst = server.review_list()
    by = {i["title"]: i for i in lst["items"]}
    assert by["New thing for Acme Billing"]["suggestion"]["company"]["name"] == "Acme"
    assert by["New thing for Acme Billing"]["suggestion"]["product"]["name"] == "Billing"
    assert by["Unrelated"]["suggestion"]["strength"] == "none"
    assert by["Payment retries"]["similar"] and by["Payment retries"]["similar"][0]["title"] == "Retry payments"
    assert by["Unrelated"]["similar"] == []


def test_push_is_all_or_nothing_and_keeps_the_list_on_failure(env, alice):
    env.sign_in(alice)
    server.keep([item("One", "first decision"), item("Two", "second decision")], chat_id="c", ctx=FakeCtx("claude-code"))
    lst = server.review_list()
    payload = push_payload(lst, "Acme")
    payload["items"][1]["company"] = {"id": str(uuid.uuid4())}                   # unknown company
    with pytest.raises(PushRefused, match="Nothing was pushed"):
        review_push.push(env.api(), env.settings, payload)
    assert queue.count() == 2 and env.api().select("decisions") == []
    assert env.api().select("companies") == []                                    # "Acme" from item 1 rolled back too


def test_push_refuses_an_item_without_a_company_before_touching_the_database(env, alice):
    env.sign_in(alice)
    server.keep([item("One", "first decision")], chat_id="c", ctx=FakeCtx("claude-code"))
    payload = push_payload(server.review_list(), "Acme")
    payload["items"][0]["company"] = {"name": "   "}
    with pytest.raises(PushRefused, match="incomplete"):
        review_push.push(env.api(), env.settings, payload)
    assert queue.count() == 1


def test_keeps_made_during_review_wait_for_the_next_review(env, alice):
    env.sign_in(alice)
    server.keep([item("Before", "kept before the review")], chat_id="c1", ctx=FakeCtx("claude-code"))
    lst = server.review_list()
    server.keep([item("During", "kept while the review was open")], chat_id="c2", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(lst, "Acme"))
    assert [i["title"] for i in queue.read_all()] == ["During"]
    assert [i["title"] for i in server.review_list()["items"]] == ["During"]


def test_retrying_the_same_push_creates_no_duplicates(env, alice):
    env.sign_in(alice)
    server.keep([item("Once", "only once please")], chat_id="c", ctx=FakeCtx("claude-code"))
    payload = push_payload(server.review_list(), "Acme")
    review_push.push(env.api(), env.settings, payload)
    again = review_push.push(env.api(), env.settings, payload)
    assert again["saved"] == 0 and again["skipped"] == 1
    assert len(env.api().select("decisions")) == 1


def test_unticked_desktop_drafts_are_deleted_for_good(env, alice):
    env.sign_in(alice)
    server.keep([item("Keep me", "keep this one"), item("Drop me", "drop this one")], chat_id="d", ctx=FakeCtx("claude-ai"))
    lst = server.review_list()
    drop = next(i["keep_id"] for i in lst["items"] if i["title"] == "Drop me")
    res = server.push_review(**push_payload(lst, "Acme", drop=[drop]))
    assert res["saved"] == 1 and res["removed"] == 1
    assert [d["title"] for d in env.api().select("decisions")] == ["Keep me"]
    assert server.review_list()["items"] == []                                    # and it does not come back


# ---- folders, answering, hiding ---------------------------------------------------------------------------

def test_linking_a_folder_lets_teammates_recognise_the_company(env, alice, bob, tmp_path):
    repo = tmp_path / "billing-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:Acme/Billing.git"], check=True)

    env.sign_in(alice)
    server.keep([item("Seed", "seed decision")], chat_id="c", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(server.review_list(), "Acme", "Billing"))
    assert server.resolve_context("fix the build", folder=str(repo))["strength"] == "none"
    linked = server.link_folder(str(repo), "Acme", "Billing")
    assert linked["linked"] == "github.com/acme/billing"

    env.sign_in(bob)
    r = server.resolve_context("fix the build", folder=str(repo))
    assert r["strength"] == "strong" and r["company"]["name"] == "Acme" and r["product"]["name"] == "Billing"
    assert "folder" in r["evidence"]


def test_unknown_company_or_product_is_a_clear_error(env, alice):
    env.sign_in(alice)
    server.keep([item("Seed", "seed decision")], chat_id="c", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(server.review_list(), "Acme", "Billing"))
    with pytest.raises(ValueError, match="No company called 'Nope'"):
        server.brief("Nope")
    with pytest.raises(ValueError, match="no product called 'Ghost'"):
        server.brief("Acme", "Ghost")
    with pytest.raises(ValueError, match="Say which company"):
        server.search("anything")


def test_superchatall_searches_every_company_and_labels_them(env, alice):
    env.sign_in(alice)
    server.keep([item("Acme retry", "Acme retries failed card payments three times")], chat_id="a", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(server.review_list(), "Acme", None))
    server.keep([item("Globex retry", "Globex retries failed card payments five times")], chat_id="g", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(server.review_list(), "Globex", None))
    res = server.search("retry failed card payments", all_companies=True)
    assert {r["company"] for r in res["results"]} == {"Acme", "Globex"}
    only = server.search("retry failed card payments", company="Globex")
    assert {r["company"] for r in only["results"]} == {"Globex"}


def test_hidden_decisions_disappear_from_search_for_everyone_else(env, su, alice, bob):
    env.sign_in(alice)
    server.keep([item("Hide me", "temporary workaround for the export bug")], chat_id="c", ctx=FakeCtx("claude-code"))
    server.push_review(**push_payload(server.review_list(), "Acme", None))
    did = env.api().select("decisions", select="id")[0]["id"]
    env.api().rpc("hide_decision", {"p_id": did})
    env.sign_in(bob)
    assert server.search("export bug workaround", company="Acme")["results"] == []


def test_keyword_only_mode_works_when_the_embedding_model_is_unavailable(env, alice, monkeypatch):
    from superchat.search import embed
    monkeypatch.setattr(embed, "_model", lambda s: (_ for _ in ()).throw(embed.EmbeddingUnavailable("offline")))
    env.sign_in(alice)
    server.keep([item("Offline note", "Invoices use net-30 terms")], chat_id="c", ctx=FakeCtx("claude-code"))
    res = server.push_review(**push_payload(server.review_list(), "Acme", None))
    assert res["embeddings"].startswith("skipped")
    found = server.search("net-30", company="Acme")
    assert found["mode"] == "keyword only" and found["results"][0]["title"] == "Offline note"


def test_vault_sync_through_the_real_api_and_automatic_refresh_after_push(env, alice, tmp_path, monkeypatch):
    vault_dir = tmp_path / "vault"
    monkeypatch.setenv("SUPERCHAT_VAULT", str(vault_dir))
    env.sign_in(alice)
    server.keep([item("Retry payments", "Retry three times then email", reason="temporary declines"),
                 item("Always UTC", "Store timestamps in UTC")], chat_id="c", ctx=FakeCtx("claude-code"))
    lst = server.review_list()
    items = push_payload(lst, "Acme", "Billing")["items"]
    items[1]["product"] = None
    first = server.push_review(lst["cutoff"], items)
    assert "vault" not in first                                   # no vault folder yet: nothing is created uninvited

    out = server.vault_sync()                                      # explicit sync creates it
    assert out["files"] == 3 and (vault_dir / "Acme" / "Acme.md").exists()
    texts = {p.name: p.read_text(encoding="utf-8") for p in vault_dir.rglob("*.md")}
    retry = next(t for n, t in texts.items() if "Retry payments" in n)
    assert 'product: "Billing"' in retry and 'author: "alice@acme.test"' in retry and "temporary declines" in retry

    server.keep([item("New one", "A later decision")], chat_id="c2", ctx=FakeCtx("claude-code"))
    lst2 = server.review_list()
    second = server.push_review(lst2["cutoff"], push_payload(lst2, "Acme", None)["items"])
    assert second["vault"]["files"] == 4                           # refreshed automatically after the push
