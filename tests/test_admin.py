"""`superchat admin`: reading credentials from superchat.env, and installing / resetting the database safely."""
import json

import psycopg
import pytest

from conftest import ADMIN_DSN, AUTH_STUB
from superchat import admin, cli

DB = "superchat_admin_test"
CONN = {"host": "localhost", "port": 5433, "dbname": DB, "user": "postgres", "password": "localdev"}

# The previous knowledge-base app: its tables, with the vector extension installed in `public` (the trap).
OLD_APP = """
create extension if not exists vector;
create extension if not exists "uuid-ossp";
create table employees (id uuid primary key default uuid_generate_v4(), email text unique not null, password_hash text);
create table knowledge_articles (id uuid primary key default uuid_generate_v4(), problem text, embedding vector(1536));
create table approval_logs (id uuid primary key default uuid_generate_v4(), article_id uuid references knowledge_articles(id));
create function old_helper() returns int language sql as $$ select 1 $$;
insert into employees (email) values ('old1@x.test'), ('old2@x.test');
insert into knowledge_articles (problem) values ('old problem');
"""


@pytest.fixture()
def db():
    try:
        root = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=5)
    except Exception as e:
        pytest.skip(f"no test Postgres: {e}")
    root.execute(f"drop database if exists {DB} with (force)")
    root.execute(f"create database {DB}")
    root.close()
    c = psycopg.connect(**CONN, autocommit=True)
    c.execute("create schema if not exists extensions")
    c.execute(AUTH_STUB)
    yield c
    c.close()


# ---- reading the env file ---------------------------------------------------------------------------

PASTED = """Only use session pooler on an IPv4 network

1
Connection string
Shared pooler
postgresql://postgres.abcdref:[YOUR-PASSWORD]@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres

YOUR-DATABASE-PASSWORD=S3cr3t!pass#1
Connection parameters
host:
aws-1-ap-northeast-2.pooler.supabase.com

port:
5432

database:
postgres

user:
postgres.abcdref
2
Install Agent Skills (optional)
"""


def test_parses_the_text_pasted_from_the_supabase_connect_panel(tmp_path):
    f = tmp_path / "superchat.env"
    f.write_text(PASTED)
    assert admin.parse_env(f) == {"host": "aws-1-ap-northeast-2.pooler.supabase.com", "port": 5432, "dbname": "postgres",
                                  "user": "postgres.abcdref", "password": "S3cr3t!pass#1"}


@pytest.mark.parametrize("key", ["SUPERCHAT_DB_URL", "DATABASE_URL", "SUPABASE_DB_URL"])
def test_parses_a_database_url_with_percent_encoded_password(tmp_path, key):
    f = tmp_path / "e.env"
    f.write_text(f'# comment\n{key}="postgresql://postgres.ref:p%40ss%2Fw0rd@host.example.com:6543/mydb"\n')
    assert admin.parse_env(f) == {"host": "host.example.com", "port": 6543, "dbname": "mydb", "user": "postgres.ref", "password": "p@ss/w0rd"}


def test_parses_libpq_style_variables(tmp_path):
    f = tmp_path / "e.env"
    f.write_text("PGHOST=h\nPGPORT=5433\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=pw\n")
    assert admin.parse_env(f) == {"host": "h", "port": 5433, "dbname": "d", "user": "u", "password": "pw"}


def test_missing_pieces_are_named_and_the_file_is_never_echoed(tmp_path):
    f = tmp_path / "e.env"
    f.write_text("host:\nh.example.com\nuser:\nu\n")
    with pytest.raises(admin.AdminError, match="password") as e:
        admin.parse_env(f)
    assert "h.example.com" not in str(e.value)
    with pytest.raises(admin.AdminError, match="not found"):
        admin.parse_env(tmp_path / "nope.env")


def test_wrong_password_gives_a_fixable_message(db):
    with pytest.raises(admin.AdminError, match="Reset database password"):
        admin.connect({**CONN, "password": "definitely-wrong"})


# ---- install and reset -----------------------------------------------------------------------------------

def test_clean_database_installs_and_seeds_admins(db):
    r = admin.init(db, admins=["Boss@Acme.Test"])
    assert r["schema_version"] == "1" and r["admins"] == ["boss@acme.test"]
    assert set(r["tables_now"]) == {"members", "admin_emails", "companies", "products", "folder_links", "decisions",
                                    "decision_conflicts", "decision_history", "push_batches"}
    assert db.execute("select email from public.admin_emails").fetchall() == [("boss@acme.test",)]
    assert admin.inventory(db)["superchat_installed"] is True


def test_old_app_data_blocks_a_plain_install_and_nothing_changes(db):
    db.execute(OLD_APP)
    with pytest.raises(admin.AdminError, match="old app's data") as e:
        admin.init(db)
    assert "approval_logs" in str(e.value) and "vector" in str(e.value)
    assert db.execute("select count(*) from public.employees").fetchone()[0] == 2
    assert not admin.inventory(db)["superchat_installed"]


def test_reset_needs_explicit_confirmation(db):
    db.execute(OLD_APP)
    with pytest.raises(admin.AdminError, match="--yes"):
        admin.init(db, reset=True)
    assert db.execute("select count(*) from public.employees").fetchone()[0] == 2


def test_reset_wipes_old_public_objects_and_installs_without_touching_users_or_other_schemas(db):
    db.execute(OLD_APP)
    db.execute("create schema keepme; create table keepme.t (x int); insert into keepme.t values (7)")
    db.execute("insert into auth.users (email) values ('existing@acme.test')")
    r = admin.init(db, reset=True, admins=["owner@acme.test"], assume_yes=True)

    assert r["dropped_tables"] == {"employees": 2, "knowledge_articles": 1, "approval_logs": 0}
    assert "employees" not in r["tables_now"] and "decisions" in r["tables_now"]
    assert db.execute("select to_regproc('public.old_helper') is null").fetchone()[0]            # old function gone
    assert admin.inventory(db)["extensions_in_public"] == []                                      # old vector/uuid-ossp gone
    assert db.execute("select n.nspname from pg_extension e join pg_namespace n on n.oid=e.extnamespace "
                      "where e.extname='vector'").fetchone()[0] == "extensions"                   # new one in the right place
    assert db.execute("select count(*) from keepme.t").fetchone()[0] == 1                         # other schema untouched
    assert db.execute("select email from auth.users").fetchall() == [("existing@acme.test",)]     # sign-in users untouched
    assert db.execute("select count(*) from public.members").fetchone()[0] == 1                   # and became members


def test_running_init_again_is_harmless(db):
    admin.init(db, admins=["a@x.test"])
    db.execute("insert into auth.users (email) values ('p@x.test')")
    again = admin.init(db, admins=["a@x.test"])
    assert again["schema_version"] == "1" and db.execute("select count(*) from public.admin_emails").fetchone()[0] == 1
    assert db.execute("select count(*) from public.members").fetchone()[0] == 1


def test_installed_schema_really_works_after_a_reset(db):
    """The reset path must leave a database the app can actually use."""
    db.execute(OLD_APP)
    admin.init(db, reset=True, assume_yes=True)
    uid = db.execute("insert into auth.users (email) values ('a@x.test') returning id").fetchone()[0]
    db.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps({"sub": str(uid), "email": "a@x.test"}),))
    db.execute("set role authenticated")
    res = db.execute("select public.push_review('d', now(), %s::jsonb, '{}')",
                     (json.dumps([{"keep_id": "00000000-0000-0000-0000-000000000001", "title": "t", "decision": "d",
                                   "company": {"name": "Acme"}}]),)).fetchone()[0]
    assert res["saved"] == 1
    db.execute("reset role")


# ---- the command line --------------------------------------------------------------------------------------

def test_cli_status_and_init_from_an_env_file(db, tmp_path, capsys):
    db.execute(OLD_APP)
    env = tmp_path / "superchat.env"
    env.write_text("PGHOST=localhost\nPGPORT=5433\nPGDATABASE=%s\nPGUSER=postgres\nPGPASSWORD=localdev\n" % DB)
    assert cli.main(["admin", "status", "--env", str(env)]) == 0
    assert "employees" in capsys.readouterr().out
    assert cli.main(["admin", "init", "--env", str(env)]) == 2                    # old data, no --reset
    assert "--reset --yes" in capsys.readouterr().err
    assert cli.main(["admin", "init", "--env", str(env), "--reset", "--yes", "--admin-email", "me@x.test"]) == 0
    assert json.loads(capsys.readouterr().out)["admins"] == ["me@x.test"]


def test_packaged_schema_matches_the_migrations():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    packaged = (root / "src" / "superchat" / "assets" / "supabase" / "setup.sql").read_text(encoding="utf-8")
    assert packaged == (root / "supabase" / "setup.sql").read_text(encoding="utf-8"), "run: python supabase/build_setup.py"
    for m in sorted((root / "supabase" / "migrations").glob("*.sql")):
        assert m.read_text(encoding="utf-8") in packaged


def test_env_value_and_the_restructured_owner_file_format(tmp_path):
    f = tmp_path / "superchat.env"
    f.write_text("# header\nSUPERCHAT_SUPABASE_URL=https://ref.supabase.co\nSUPERCHAT_SUPABASE_KEY=\n"
                 "PGHOST=h.example.com\nPGPORT=5432\nPGDATABASE=postgres\nPGUSER=postgres.ref\nPGPASSWORD=p#ss w0rd=1\n"
                 "SUPERCHAT_ADMIN_EMAIL=Boss@Acme.test\n")
    assert admin.env_value(f, "SUPERCHAT_ADMIN_EMAIL") == "Boss@Acme.test"
    assert admin.env_value(f, "SUPERCHAT_SUPABASE_KEY") == "" and admin.env_value(f, "NOPE") == ""
    assert admin.parse_env(f)["password"] == "p#ss w0rd=1"            # '#', spaces and '=' survive
    assert admin.parse_env(f)["host"] == "h.example.com"
