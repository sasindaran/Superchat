"""
Database test harness.

Runs the REAL migrations in supabase/migrations/ against a throwaway Postgres+pgvector
database, with a small stand-in for Supabase's `auth` schema (auth.users, auth.uid(),
auth.jwt(), and the `anon` / `authenticated` roles). Tests then act as different people
by switching role and setting the JWT claims, exactly how PostgREST does it.

Needs Postgres with pgvector reachable at SUPERCHAT_TEST_DSN, e.g. the docker container:
    docker run -d --name kb-postgres -e POSTGRES_PASSWORD=localdev -p 5433:5432 pgvector/pgvector:pg17
"""
import contextlib
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
ADMIN_DSN = os.environ.get("SUPERCHAT_TEST_DSN", "postgresql://postgres:localdev@localhost:5433/postgres")
TEST_DB = "superchat_test"

AUTH_STUB = """
create schema if not exists auth;
create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text,
  raw_user_meta_data jsonb default '{}'::jsonb
);
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(auth.jwt() ->> 'sub', '')::uuid $$;
do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
grant usage on schema auth, extensions to anon, authenticated;
grant select on auth.users to authenticated;
grant execute on all functions in schema extensions to anon, authenticated;
"""


def _dsn_for(db: str) -> str:
    base, _, _ = ADMIN_DSN.rpartition("/")
    return f"{base}/{db}"


@pytest.fixture(scope="session")
def dsn():
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"no test Postgres reachable ({e}); start the docker container, see tests/conftest.py")
    admin.execute(f"drop database if exists {TEST_DB} with (force)")
    admin.execute(f"create database {TEST_DB}")
    admin.close()

    with psycopg.connect(_dsn_for(TEST_DB), autocommit=True) as c:
        c.execute("create schema if not exists extensions")
        c.execute("create extension if not exists vector with schema extensions")
        c.execute(AUTH_STUB)
        for m in MIGRATIONS:
            c.execute(m.read_text(encoding="utf-8"))
    return _dsn_for(TEST_DB)


@pytest.fixture()
def su(dsn):
    """Superuser connection (setup / inspection). Data is wiped before every test."""
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute(
        "truncate public.push_batches, public.decision_history, public.decision_conflicts, "
        "public.decisions, public.folder_links, public.products, public.companies, "
        "public.admin_emails, public.members restart identity cascade"
    )
    conn.execute("delete from auth.users")
    yield conn
    conn.close()


class Person:
    def __init__(self, dsn, uid, email):
        self.dsn, self.id, self.email = dsn, uid, email

    @contextlib.contextmanager
    def session(self, commit=True):
        """Act as this person (role `authenticated` + their JWT claims) inside a transaction."""
        conn = psycopg.connect(self.dsn, autocommit=False)
        try:
            conn.execute("set local role authenticated")
            claims = json.dumps({"sub": str(self.id), "email": self.email, "role": "authenticated"})
            conn.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
            yield conn
            conn.commit() if commit else conn.rollback()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


@pytest.fixture()
def make_person(dsn, su):
    def _make(name, admin=False):
        email = f"{name}@acme.test"
        uid = su.execute("insert into auth.users (email) values (%s) returning id", (email,)).fetchone()[0]
        if admin:
            su.execute("insert into public.admin_emails (email) values (%s)", (email,))
        return Person(dsn, uid, email)
    return _make


@pytest.fixture()
def alice(make_person):
    return make_person("alice")


@pytest.fixture()
def bob(make_person):
    return make_person("bob")


@pytest.fixture()
def root(make_person):
    return make_person("root", admin=True)


@contextlib.contextmanager
def anon_session(dsn):
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        conn.execute("set local role anon")
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture()
def anon(dsn):
    return lambda: anon_session(dsn)


def vec(*hot, dim=384):
    """A 384-number vector with 1.0 at the given positions (easy to reason about similarity)."""
    v = [0.0] * dim
    for i in hot:
        v[i] = 1.0
    return v


def item(title="Retry failed payments 3 times", company="Acme", product=None, **over):
    base = {
        "keep_id": str(uuid.uuid4()),
        "chat_id": "chat-1",
        "kind": "decision",
        "title": title,
        "decision": "Retry a failed card payment three times, then email the client.",
        "condition": "card is declined",
        "reason": "most declines are temporary",
        "original_text": "we retry thrice then mail them",
        "source_agent": "claude-code",
        "folder_key": "github.com/acme/billing",
        "company": {"name": company},
        "product": {"name": product} if product else None,
        "embedding": None,
        "embedding_model": None,
        "conflicts": [],
    }
    base.update(over)
    return base


def push(conn, items, device="dev-1", remove=(), cutoff="2026-11-25T12:00:00+00:00"):
    row = conn.execute(
        "select public.push_review(%s, %s::timestamptz, %s::jsonb, %s::uuid[])",
        (device, cutoff, json.dumps(items), list(remove)),
    ).fetchone()
    return row[0]
