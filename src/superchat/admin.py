"""
Owner only: install the Superchat schema into the team's Supabase database, optionally wiping the old contents of
the `public` schema first. Uses the database credentials from a local env file (superchat.env), which is never
committed. Employees never need any of this.

The env file may be a normal KEY=VALUE file (DATABASE_URL / SUPERCHAT_DB_URL, or PGHOST/PGUSER/...) or the text
pasted from Supabase's "Connect" panel (host:, port:, database:, user: lines plus a line holding the password).
"""
import re
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse

URL_KEYS = ("SUPERCHAT_DB_URL", "DATABASE_URL", "SUPABASE_DB_URL")


class AdminError(Exception):
    pass


def parse_env(path) -> dict:
    """Connection settings (host, port, dbname, user, password) from an env file."""
    p = Path(path)
    if not p.exists():
        raise AdminError(f"{p} not found")
    lines = [ln.rstrip("\r\n") for ln in p.read_text(encoding="utf-8").splitlines()]
    pairs = {}
    for ln in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_\-]*)\s*=\s*(.*?)\s*$", ln)
        if m:
            pairs[m.group(1)] = m.group(2).strip().strip("\"'")

    pw = next((v for k, v in pairs.items() if re.search(r"(?i)password", k) and v), None)
    conn = {}
    for k in URL_KEYS:                                     # a full URI wins
        if pairs.get(k):
            u = urlparse(pairs[k])
            conn = {"host": u.hostname, "port": u.port or 5432, "dbname": (u.path or "/postgres").lstrip("/") or "postgres",
                    "user": unquote(u.username or ""), "password": unquote(u.password or "") or pw}
            break
    if not conn:
        def labelled(label):                               # "host:" then the value on a following line
            for i, ln in enumerate(lines):
                if ln.strip().lower() == label:
                    return next((x.strip() for x in lines[i + 1:] if x.strip()), None)
            return None
        conn = {"host": pairs.get("PGHOST") or labelled("host:"), "port": pairs.get("PGPORT") or labelled("port:") or 5432,
                "dbname": pairs.get("PGDATABASE") or labelled("database:") or "postgres",
                "user": pairs.get("PGUSER") or labelled("user:"), "password": pairs.get("PGPASSWORD") or pw}
    missing = [k for k in ("host", "user", "password") if not conn.get(k)]
    if missing:
        raise AdminError(f"could not find the database {', '.join(missing)} in {p.name}")
    conn["port"] = int(conn["port"])
    return conn


def env_value(path, key: str) -> str:
    """One KEY=VALUE from an env file ('' when absent or empty)."""
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*(.*?)\s*$", ln)
        if m:
            return m.group(1).strip().strip("\"'")
    return ""


def connect(conn: dict):
    import psycopg
    local = conn["host"] in ("localhost", "127.0.0.1")
    try:
        return psycopg.connect(**conn, connect_timeout=20, autocommit=True, sslmode="prefer" if local else "require")
    except psycopg.OperationalError as e:
        msg = str(e).strip().splitlines()[0]
        if "password authentication failed" in msg:
            raise AdminError("the database rejected that password. Reset it in Supabase (Project Settings > Database > "
                             "Reset database password) and update the password line in the env file.") from e
        raise AdminError(f"could not connect: {msg}") from e


def inventory(c) -> dict:
    tables = [r[0] for r in c.execute("select tablename from pg_tables where schemaname='public' order by 1").fetchall()]
    counts = {t: c.execute(f'select count(*) from public."{t}"').fetchone()[0] for t in tables}
    ext = [r[0] for r in c.execute(
        "select e.extname from pg_extension e join pg_namespace n on n.oid=e.extnamespace "
        "where n.nspname='public' and e.extname in ('vector','uuid-ossp') order by 1").fetchall()]
    has_auth = c.execute("select to_regclass('auth.users') is not null").fetchone()[0]
    users = c.execute("select count(*) from auth.users").fetchone()[0] if has_auth else None
    installed = c.execute("select to_regproc('public.superchat_version') is not null").fetchone()[0]
    return {"tables": counts, "extensions_in_public": ext, "auth_users": users, "superchat_installed": installed}


RESET_SQL = """
do $$
declare r record;
begin
  -- the old app put extensions in `public`; Superchat needs `vector` in `extensions`
  for r in select e.extname from pg_extension e join pg_namespace n on n.oid = e.extnamespace
           where n.nspname = 'public' and e.extname in ('vector', 'uuid-ossp') loop
    execute format('drop extension if exists %I cascade', r.extname);
  end loop;
  for r in select tablename from pg_tables where schemaname = 'public' loop
    execute format('drop table if exists public.%I cascade', r.tablename);
  end loop;
  for r in select viewname from pg_views where schemaname = 'public' loop
    execute format('drop view if exists public.%I cascade', r.viewname);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e') loop
    execute format('drop function if exists %s cascade', r.sig);
  end loop;
  for r in select t.typname from pg_type t join pg_namespace n on n.oid = t.typnamespace
           where n.nspname = 'public' and t.typtype in ('e', 'd') loop
    execute format('drop type if exists public.%I cascade', r.typname);
  end loop;
end $$;
"""


def setup_sql() -> str:
    return resources.files("superchat").joinpath("assets", "supabase", "setup.sql").read_text(encoding="utf-8")


def init(c, reset: bool = False, admins=(), assume_yes: bool = False) -> dict:
    inv = inventory(c)
    old = [t for t in inv["tables"] if t not in ("members", "admin_emails", "companies", "products", "folder_links", "decisions",
                                                 "decision_conflicts", "decision_history", "push_batches")]
    if (old or inv["extensions_in_public"]) and not reset:
        raise AdminError("this database still holds the old app's data (tables: " + (", ".join(old) or "none") +
                         "; extensions in public: " + (", ".join(inv["extensions_in_public"]) or "none") +
                         "). Re-run with --reset --yes to wipe the `public` schema first. The `auth` users are never touched.")
    if reset and not assume_yes:
        raise AdminError("--reset deletes everything in the `public` schema. Add --yes to confirm.")
    dropped = {}
    if reset:
        dropped = dict(inv["tables"])
        c.execute(RESET_SQL)
    c.execute(setup_sql())
    for email in admins:
        c.execute("insert into public.admin_emails (email) values (%s) on conflict do nothing", (email.strip().lower(),))
    version = c.execute("select public.superchat_version()").fetchone()[0]
    after = inventory(c)
    return {"schema_version": version, "dropped_tables": dropped, "tables_now": sorted(after["tables"]),
            "auth_users": after["auth_users"], "admins": [a.strip().lower() for a in admins]}


def configure_auth(token: str, project_ref: str, client=None) -> dict:
    """
    Lock the project's sign-in to invited people and allow Superchat's local return addresses, using a short-lived
    Supabase personal access token (https://supabase.com/dashboard/account/tokens). Existing allowed addresses are kept.
    """
    import httpx
    from . import auth
    if not token.startswith("sbp_"):
        raise AdminError("that does not look like a Supabase personal access token (it starts with sbp_)")
    http = client or httpx.Client(timeout=60)
    url = f"https://api.supabase.com/v1/projects/{project_ref}/config/auth"
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    cur = http.get(url, headers=h)
    if cur.status_code in (401, 403):
        raise AdminError("Supabase refused the access token (expired, or not allowed to manage this project)")
    if cur.status_code >= 400:
        raise AdminError(f"could not read the project's sign-in settings (HTTP {cur.status_code})")
    cfg = cur.json()
    existing = [x.strip() for x in (cfg.get("uri_allow_list") or "").split(",") if x.strip()]
    allow = existing + [u for u in auth.ALLOW_LIST if u not in existing]
    r = http.patch(url, headers=h, json={"disable_signup": True, "uri_allow_list": ",".join(allow)})
    if r.status_code >= 400:
        raise AdminError(f"Supabase did not accept the change: {r.text[:200]}")
    return {"public_signup_disabled": True, "return_addresses_allowed": len(auth.ALLOW_LIST),
            "kept_existing_addresses": len(existing), "emails_per_hour": cfg.get("rate_limit_email_sent"),
            "custom_smtp": bool(cfg.get("smtp_host")), "email_templates_editable": bool(cfg.get("smtp_host"))}
