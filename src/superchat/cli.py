"""
superchat: command line.

    superchat login --email you@company.com        # emails you a 6-digit code
    superchat login --email you@company.com --code 123456
    superchat whoami | logout | status | doctor | set | mcp
Every command is non-interactive (flags only) so an agent can run it start to finish.
"""
import argparse
import json
import sys

import httpx

from . import __version__, auth, config, paths, state
from .capture import queue
from .admin import AdminError
from .db import Api, ApiError

OK, BAD, WARN = "[ok]  ", "[FAIL]", "[warn]"


def _print(tag: str, msg: str, hint: str = "") -> None:
    print(f"{tag} {msg}")
    if hint:
        print(f"       -> {hint}")


def check_supabase(s: config.Settings, http: httpx.Client | None = None) -> list:
    """Returns [(tag, message, hint)] describing whether the Supabase project is reachable and set up."""
    http = http or httpx.Client(timeout=20)
    out = []
    # 1. does the project (the default URL, or the user's override) exist at all?
    try:
        r = http.get(f"{s.supabase_url}/auth/v1/health", headers={"apikey": s.supabase_key} if s.supabase_key else {})
        if r.status_code == 200:
            out.append((OK, f"Supabase project reachable: {s.supabase_url}", ""))
        elif r.status_code in (401, 403):
            hint = "" if s.supabase_key else "The project exists, but no publishable key is set. Run: superchat set --key <publishable key>"
            out.append((OK if s.supabase_key else WARN, f"Supabase project exists: {s.supabase_url} (it wants an API key)", hint))
            if s.supabase_key:
                out.append((BAD, "The publishable key was rejected", "Copy it again: Supabase > Project Settings > API Keys"))
                return out
        else:
            out.append((BAD, f"Unexpected answer from {s.supabase_url} (HTTP {r.status_code})", "Check the URL"))
            return out
    except httpx.HTTPError as e:
        out.append((BAD, f"Cannot reach {s.supabase_url}: {e}", "Check the internet connection and the URL"))
        return out
    if not s.supabase_key:
        return out
    # 2. are the Superchat tables and functions installed?
    try:
        v = Api(s, http).schema_version()
        if str(v) == s.schema_version:
            out.append((OK, f"Database schema installed (version {v})", ""))
        else:
            out.append((WARN, f"Database schema is version {v}, this app expects {s.schema_version}",
                        "Ask the owner to run supabase/setup.sql again"))
    except ApiError as e:
        out.append((BAD, "Superchat tables are not installed in this Supabase project",
                    f"The owner must run supabase/setup.sql in the SQL editor ({e})"))
    return out


def doctor(deep: bool = False) -> int:
    s = config.load()
    bad = 0
    _print(OK, f"superchat {__version__}; data folder {paths.home()}")
    if not s.configured:
        _print(WARN, "Supabase publishable key is not set", "superchat set --key <publishable key>")
    for tag, msg, hint in check_supabase(s):
        _print(tag, msg, hint)
        bad += tag == BAD
    me = auth.whoami()
    if me:
        _print(OK, f"Signed in as {me['email']}")
    else:
        _print(WARN, "Not signed in", "superchat login --email you@company.com, then click the emailed link on this computer")
    n = queue.count()
    _print(OK, f"{n} kept decision(s) waiting for review on this computer")
    from .agents import claude_code, claude_desktop
    if claude_code.detected():
        st = claude_code.status()
        _print(OK if st["all_skills"] and st["hooks"] else WARN,
               f"Claude Code: {len(st['skills'])}/{len(claude_code.SKILLS)} commands installed, hooks {'on' if st['hooks'] else 'off'}",
               "" if st["all_skills"] and st["hooks"] else "Run: superchat setup")
    for path, ok in claude_desktop.status():
        _print(OK if ok else WARN, f"Claude Desktop config {'has' if ok else 'is missing'} superchat: {path}",
               "" if ok else "Run: superchat setup, then restart Claude Desktop")
    if deep:
        from .search import embed
        try:
            embed.embed(s, ["health check"])
            _print(OK, f"Embedding model ready ({s.embedding_tag}, {s.embedding_dim} numbers)")
        except embed.EmbeddingUnavailable as e:
            _print(BAD, str(e), "Search falls back to keywords until the model downloads")
            bad += 1
    return 1 if bad else 0


def login_in_background(s: config.Settings, email: str, wait: int = 900) -> None:
    """Start a listener in a detached process, then have Supabase email the link; returns immediately."""
    import socket
    import subprocess
    import time as _t
    ports = list(auth.LOOPBACK_PORTS)
    probe = auth.LinkLogin(tuple(ports))            # find a free port, then free it for the background process
    port, nonce = probe.port, probe.nonce
    probe.close()
    log = paths.home() / "login.log"                # the background process writes here, so failures can be read
    out = open(log, "ab")
    cmd = [sys.executable, "-m", "superchat", "login-serve", "--port", str(port), "--nonce", nonce, "--wait", str(wait)]
    kw = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out, "close_fds": True}
    if sys.platform == "win32":
        # The `superchat.exe` launcher keeps its children in a Windows job that is torn down when it exits, so
        # the listener must break away from it to outlive this command.
        detached = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            child = subprocess.Popen(cmd, creationflags=detached | 0x01000000, **kw)   # + CREATE_BREAKAWAY_FROM_JOB
        except OSError:                               # the job does not allow breaking away
            child = subprocess.Popen(cmd, creationflags=detached, **kw)
    else:
        child = subprocess.Popen(cmd, start_new_session=True, **kw)
    out.close()
    deadline = _t.time() + 30                        # wait until it is really listening before emailing the link
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.25).close()
            break
        except OSError:
            if child.poll() is not None or _t.time() > deadline:
                tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
                raise auth.AuthError("Could not start the local sign-in listener"
                                     + (f": {' / '.join(tail)}" if tail else "") + f" (log: {log}). No email was sent.")
            _t.sleep(0.15)
    auth.request_code(s, email, redirect_to=f"http://127.0.0.1:{port}/cb/{nonce}")


def _agents(choice: str) -> list:
    from .agents import claude_code, claude_desktop
    table = {"claude-code": claude_code, "claude-desktop": claude_desktop}
    if choice == "auto":
        return [(n, m) for n, m in table.items() if m.detected()]
    wanted = [x.strip() for x in choice.split(",") if x.strip()]
    unknown = [x for x in wanted if x not in table]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)}. Choose from: {', '.join(table)}")
    return [(n, table[n]) for n in wanted]


def setup(url=None, key=None, agents="auto") -> int:
    from .agents.common import ConfigError
    if url or key:
        config.save_user(supabase_url=url, supabase_key=key)
    s = config.load()
    default = config._packaged()["supabase_url"]
    print(f"Supabase project: {s.supabase_url}" + (" (the team default; change with --url)" if s.supabase_url == default else ""))
    print("Publishable key: " + ("set" if s.supabase_key else "NOT set (get it from Supabase > Project Settings > API Keys, "
                                 "then run: superchat set --key <key>)"))
    chosen = _agents(agents)
    if not chosen:
        print("No supported app found. Install Claude Code or Claude Desktop first.")
        return 1
    failed = False
    for name, mod in chosen:
        try:
            for step in mod.install():
                print(f"  {name}: {step}")
        except ConfigError as e:
            failed = True
            print(f"  {name}: NOT done: {e}")
    print("\nNext: restart Claude Desktop / start a new Claude Code session, then sign in:\n"
          "  superchat login --email you@company.com   (then click the emailed link on this computer)\n"
          "  superchat whoami\n"
          "  superchat doctor")
    return 1 if failed else 0


def uninstall() -> int:
    for name, mod in _agents("auto"):
        for step in mod.uninstall():
            print(f"  {name}: {step}")
    print("Removed. Your sign-in, queue and settings were left in place.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="superchat", description="Shared decision memory for Claude chats.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("login", help="sign in with an emailed code")
    lg.add_argument("--email", required=True)
    lg.add_argument("--code", help="the code from the email, if your email shows one (custom email setups only)")
    lg.add_argument("--wait", type=int, default=0, help="stay and wait this many seconds for the link to be clicked "
                    "(default: finish in the background and return at once)")
    ls = sub.add_parser("login-serve", help=argparse.SUPPRESS)
    ls.add_argument("--port", type=int, required=True)
    ls.add_argument("--nonce", required=True)
    ls.add_argument("--wait", type=int, default=900)
    sub.add_parser("logout")
    sub.add_parser("whoami")
    sub.add_parser("status", help="how many kept decisions are waiting")
    dc = sub.add_parser("doctor", help="check that everything works")
    dc.add_argument("--deep", action="store_true", help="also load the embedding model")
    st = sub.add_parser("set", help="change settings (they override the built-in defaults)")
    st.add_argument("--url")
    st.add_argument("--key")
    st.add_argument("--reset-url", action="store_true", help="go back to the built-in default URL")
    sub.add_parser("mcp", help="run the MCP server (agents start this)")
    hk = sub.add_parser("hook", help="Claude Code hook entry point (used internally)")
    hk.add_argument("event", choices=["session-start", "user-prompt", "pre-tool-use"])
    sc = sub.add_parser("strict", help="switch strict mode (no knowledge base for answers) for one session")
    sc.add_argument("state", choices=["on", "off", "status"])
    sc.add_argument("--session", required=True)
    su = sub.add_parser("setup", help="install into Claude Code / Claude Desktop")
    su.add_argument("--url", help="Supabase project URL (default: the team's)")
    su.add_argument("--key", help="Supabase publishable key")
    su.add_argument("--agents", default="auto", help="auto, or a comma list of: claude-code,claude-desktop")
    ad = sub.add_parser("admin", help="owner only: install the database schema")
    ad.add_argument("action", choices=["status", "init", "auth"])
    ad.add_argument("--env", default="superchat.env", help="file holding the database credentials (default: superchat.env)")
    ad.add_argument("--reset", action="store_true", help="wipe the old contents of the public schema first")
    ad.add_argument("--yes", action="store_true", help="confirm --reset")
    ad.add_argument("--admin-email", action="append", default=[], help="make this email an admin (repeatable)")
    sub.add_parser("review-template", help="print the path of the review screen template")
    vs = sub.add_parser("vault", help="Obsidian copy of the knowledge base")
    vs.add_argument("action", choices=["sync", "path"])
    sub.add_parser("uninstall", help="remove everything setup added (settings and your data are kept)")

    a = p.parse_args(argv)
    try:
        if a.cmd == "mcp":
            from .mcp_server import run
            run()
            return 0
        if a.cmd == "hook":
            from .hooks import run as run_hook
            return run_hook(a.event)
        if a.cmd == "strict":
            from . import hooks
            if a.state == "on":
                hooks.strict_on(a.session)
            elif a.state == "off":
                hooks.strict_off(a.session)
            print(json.dumps({"strict": hooks.is_strict(a.session)}))
            return 0
        if a.cmd == "setup":
            return setup(a.url, a.key, a.agents)
        if a.cmd == "uninstall":
            return uninstall()
        if a.cmd == "admin" and a.action == "auth":
            from . import admin
            tok = admin.env_value(a.env, "SUPABASE_ACCESS_TOKEN")
            url = admin.env_value(a.env, "SUPERCHAT_SUPABASE_URL") or config.load().supabase_url
            if not tok:
                raise ValueError(f"put a Supabase personal access token on the SUPABASE_ACCESS_TOKEN= line of {a.env} "
                                 "(https://supabase.com/dashboard/account/tokens), then run this again; delete the token afterwards")
            print(json.dumps(admin.configure_auth(tok, url.split("//", 1)[-1].split(".", 1)[0]), indent=2))
            return 0
        if a.cmd == "admin":
            from . import admin
            conn = admin.connect(admin.parse_env(a.env))
            with conn:
                if a.action == "status":
                    print(json.dumps(admin.inventory(conn), indent=2))
                else:
                    emails = a.admin_email or [e for e in [admin.env_value(a.env, "SUPERCHAT_ADMIN_EMAIL")] if e]
                    if not emails:
                        print("note: no admin email given (--admin-email, or SUPERCHAT_ADMIN_EMAIL in the env file): "
                              "nobody will be an admin yet", file=sys.stderr)
                    print(json.dumps(admin.init(conn, a.reset, emails, a.yes), indent=2))
            return 0
        if a.cmd == "review-template":
            from importlib import resources
            print(resources.files("superchat").joinpath("assets", "review", "template.html"))
            return 0
        if a.cmd == "vault":
            from . import vault
            s = config.load()
            if a.action == "path":
                print(vault.vault_dir(s))
            else:
                print(json.dumps(vault.sync(Api(s), s)))
            return 0
        if a.cmd == "login-serve":
            r = auth.LinkLogin((a.port,), a.nonce).wait(config.load(), a.wait)
            print(f"Signed in as {r['user']['email']}.")
            return 0
        if a.cmd == "login":
            s = config.load()
            if a.code:
                r = auth.verify_code(s, a.email, a.code)
                print(f"Signed in as {r['user']['email']}.")
            elif a.wait:
                ll = auth.start_link_login(s, a.email)
                print(f"A sign-in link was emailed to {a.email.strip().lower()}. Click it in a browser on THIS computer; waiting...")
                r = ll.wait(s, a.wait)
                print(f"Signed in as {r['user']['email']}.")
            else:
                login_in_background(s, a.email)
                print(f"A sign-in link was emailed to {a.email.strip().lower()}.\n"
                      "Click it in a browser on THIS computer. Superchat finishes signing in by itself; "
                      "check with: superchat whoami")
            return 0
        if a.cmd == "logout":
            auth.logout()
            print("Signed out.")
            return 0
        if a.cmd == "whoami":
            me = auth.whoami()
            print(json.dumps({"signed_in_as": me["email"] if me else None, "supabase_url": config.load().supabase_url}))
            return 0
        if a.cmd == "status":
            print(json.dumps({"waiting_locally": queue.count(), "last_push": state.get("last_push")}))
            return 0
        if a.cmd == "doctor":
            return doctor(a.deep)
        if a.cmd == "set":
            if a.reset_url:
                config.unset_user("supabase_url")
            config.save_user(supabase_url=a.url, supabase_key=a.key)
            s = config.load()
            print(f"Supabase URL: {s.supabase_url}\nPublishable key: {'set' if s.supabase_key else 'NOT set'}")
            return 0
        p.print_help()
        return 0
    except (auth.AuthError, ApiError, AdminError, ValueError, RuntimeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
