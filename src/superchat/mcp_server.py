"""The Superchat MCP server (runs locally, started by Claude Code / Claude Desktop)."""
import sys
import uuid
from importlib import resources
from typing import Optional

from mcp.server.fastmcp import Context, FastMCP

from . import __version__, auth, config, paths, state, vault
from .capture import drafts, queue
from .capture.folders import folder_key as make_folder_key
from .context.resolve import resolve
from .db import Api, ApiError
from .review import build as review_build
from .review import push as review_push
from .search import hybrid

INSTRUCTIONS = resources.files("superchat").joinpath("instructions.md").read_text(encoding="utf-8")
mcp = FastMCP("superchat", instructions=INSTRUCTIONS)


# ---- helpers -----------------------------------------------------------------------------------

def _settings():
    return config.load()


def _api() -> Api:
    s = _settings()
    if not s.configured:
        raise ValueError("Superchat is not configured: the Supabase publishable key is missing. Run `superchat setup`.")
    return Api(s)


def _client_name(ctx: Optional[Context]) -> str:
    try:
        return (ctx.session.client_params.clientInfo.name or "").lower()
    except Exception:
        return ""


def _capture_target(ctx, settings) -> str:
    """'drafts' (Supabase, for Claude Desktop) or 'queue' (this machine, for Claude Code and others)."""
    mode = settings.capture_mode
    if mode in ("queue", "drafts"):
        return mode
    name = _client_name(ctx)
    if "code" in name:
        return "queue"
    return "drafts" if ("desktop" in name or name.startswith("claude-ai") or name == "claude") else "queue"


def _agent_label(ctx) -> str:
    n = _client_name(ctx)
    return n or "unknown-agent"


def _find_company(api: Api, ref: Optional[str]) -> Optional[dict]:
    """A company by id, name or alias."""
    if not ref:
        return None
    key = ref.strip().lower()
    for c in review_build.companies(api):
        if c["id"] == ref or c["name"].lower() == key or key in [a.lower() for a in c.get("aliases") or []]:
            return c
    raise ValueError(f"No company called '{ref}'. Use `companies` to see the list.")


def _find_product(company: dict, ref: Optional[str]) -> Optional[dict]:
    if not ref:
        return None
    key = ref.strip().lower()
    for p in company["products"]:
        if p["id"] == ref or p["name"].lower() == key or key in [a.lower() for a in p.get("aliases") or []]:
            return p
    raise ValueError(f"'{company['name']}' has no product called '{ref}'.")


# ---- sign-in -----------------------------------------------------------------------------------

_login = {"state": "idle", "error": None}


def _finish_login(ll, settings) -> None:
    try:
        ll.wait(settings, 900)
        _login.update(state="done", error=None)
    except Exception as e:
        _login.update(state="failed", error=str(e))


@mcp.tool()
def login(email: str) -> str:
    """
    Start signing in: Supabase emails a sign-in LINK to this work email. Tell the person to click it in a browser on
    THIS computer; Superchat finishes signing in by itself. Then call whoami to confirm. (If their email shows a code
    instead, ask for it and call verify_code.)
    """
    import threading
    settings = _settings()
    ll = auth.start_link_login(settings, email)
    _login.update(state="waiting", error=None)
    threading.Thread(target=_finish_login, args=(ll, settings), daemon=True, name="superchat-login-wait").start()
    return (f"A sign-in link was emailed to {email.strip().lower()}. Ask them to click it in a browser on this computer "
            "(within 15 minutes). Then call whoami to confirm.")


@mcp.tool()
def verify_code(email: str, code: str) -> str:
    """Finish signing in with the 6-digit code from the email. The session is remembered on this computer."""
    s = auth.verify_code(_settings(), email, code)
    return f"Signed in as {s['user']['email']}."


@mcp.tool()
def whoami() -> dict:
    """Who is signed in on this computer, and which Supabase project is in use."""
    s = _settings()
    out = {"signed_in_as": (auth.whoami() or {}).get("email"), "supabase_url": s.supabase_url,
           "version": __version__, "waiting_in_local_queue": queue.count()}
    if _login["state"] == "waiting":
        out["sign_in"] = "waiting for the emailed link to be clicked"
    elif _login["state"] == "failed":
        out["sign_in"] = f"failed: {_login['error']}"
    return out


@mcp.tool()
def logout() -> str:
    """Sign out on this computer."""
    auth.logout()
    return "Signed out."


# ---- capture -----------------------------------------------------------------------------------

@mcp.tool()
def chat_tag() -> str:
    """A short tag identifying this chat, for agents that have no session id. Reuse it for the whole chat."""
    return "sc-" + uuid.uuid4().hex[:6]


@mcp.tool()
def chat_contributions(chat_id: str) -> dict:
    """Decisions this chat has already contributed (waiting locally, drafted, or pushed). /keep must skip these."""
    out = {"queued": [{"title": i["title"], "decision": i["decision"]} for i in queue.for_chat(chat_id)],
           "in_database": []}
    try:
        out["in_database"] = drafts.for_chat(_api(), chat_id)
    except (auth.NotSignedIn, ValueError, ApiError) as e:
        out["database_note"] = f"could not check the shared database: {e}"
    return out


@mcp.tool()
def keep(items: list[dict], chat_id: str, folder: Optional[str] = None, ctx: Context = None) -> dict:
    """
    Keep decisions / key notes for review. `items`: [{title, decision, condition, reason, original_text, kind}]
    Use one concise item per distinct fact. Keep title short and decision self-contained; omit condition,
    reason, and original_text unless they add necessary, explicitly established information. Do not guess.
    `folder` = the project folder path (used to recognise the company later).
    Claude Code keeps them on this computer; Claude Desktop keeps them as private unsaved drafts in Supabase.
    Nothing is shared until the person reviews and pushes.
    """
    s = _settings()
    fk = make_folder_key(folder)
    agent = _agent_label(ctx)
    note = None
    if _capture_target(ctx, s) == "drafts":
        try:
            r = drafts.add(_api(), items, chat_id, agent, fk)
            where = "private drafts in Supabase"
        except (auth.NotSignedIn, ValueError, ApiError) as e:
            r = queue.add(items, chat_id, agent, fk)
            where = "this computer's queue"
            note = f"Not saved to Supabase ({e}); kept locally instead."
    else:
        r = queue.add(items, chat_id, agent, fk)
        where = "this computer's queue"
    return {"kept": len(r["added"]), "skipped_as_already_kept": r["skipped"], "stored_in": where,
            "waiting_for_review": r["waiting"], **({"note": note} if note else {})}


# ---- context, search, answering ---------------------------------------------------------------------

@mcp.tool()
def companies() -> list:
    """All companies and their products (for dropdowns and for asking 'which company is this?')."""
    return [{"id": c["id"], "name": c["name"], "aliases": c["aliases"],
             "products": [p["name"] for p in c["products"]]} for c in review_build.companies(_api())]


@mcp.tool()
def resolve_context(text: str, folder: Optional[str] = None) -> dict:
    """Which company/product does this chat belong to? strength 'strong' means there is real evidence; 'none' means ask."""
    api = _api()
    fk = make_folder_key(folder)
    link = None
    if fk:
        found = api.select("folder_links", select="company_id,product_id", folder_key=f"eq.{fk}")
        link = found[0] if found else None
    r = resolve(review_build.companies(api), link, text)
    r["folder_key"] = fk
    return r


@mcp.tool()
def link_folder(folder: str, company: str, product: Optional[str] = None) -> dict:
    """Remember that this project folder belongs to a company (and product), for the whole team."""
    api = _api()
    c = _find_company(api, company)
    p = _find_product(c, product)
    fk = make_folder_key(folder)
    me = auth.whoami()
    api.insert("folder_links", [{"folder_key": fk, "company_id": c["id"], "product_id": p["id"] if p else None,
                                 "created_by": me["id"]}], upsert_on="folder_key")
    return {"linked": fk, "company": c["name"], "product": p["name"] if p else None}


@mcp.tool()
def match(question: str, company: Optional[str] = None, product: Optional[str] = None) -> dict:
    """Is a stored decision STRONGLY related to this question? Use before answering without a command."""
    api = _api()
    c = _find_company(api, company)
    p = _find_product(c, product) if c else None
    return hybrid.match(api, _settings(), question, c["id"] if c else None, p["id"] if p else None)


@mcp.tool()
def brief(company: str, product: Optional[str] = None) -> dict:
    """A company's guidelines (company-wide decisions), the product's own decisions, and known conflicts."""
    api = _api()
    c = _find_company(api, company)
    p = _find_product(c, product)
    return api.rpc("company_brief", {"p_company": c["id"], "p_product": p["id"] if p else None})


@mcp.tool()
def search(query: str, company: Optional[str] = None, product: Optional[str] = None,
           all_companies: bool = False, limit: int = 10) -> dict:
    """Search saved decisions. One company, unless all_companies=true (/superchatall). Every result names its company."""
    api = _api()
    c = _find_company(api, company)
    if not c and not all_companies:
        raise ValueError("Say which company, or set all_companies=true.")
    p = _find_product(c, product) if c else None
    return hybrid.search(api, _settings(), query, c["id"] if c else None, p["id"] if p else None, all_companies, limit)


# ---- review ---------------------------------------------------------------------------------------

@mcp.tool()
def review_list() -> dict:
    """Everything kept and not yet pushed, with suggestions, look-alikes and the company list. Follows review/contract.md."""
    return review_build.build(_api(), _settings())


@mcp.tool()
def push_review(cutoff: str, items: list[dict], remove_keep_ids: Optional[list[str]] = None) -> dict:
    """
    The ONE push: save every ticked item and delete the un-ticked ones, all or nothing. `cutoff` is the review list's
    cutoff, unchanged. Each item needs a company; product may be empty (= company-wide).
    """
    api, settings = _api(), _settings()
    result = review_push.push(api, settings, {"cutoff": cutoff, "items": items, "remove_keep_ids": remove_keep_ids or []})
    if vault.vault_dir(settings).exists():            # keep the Obsidian copy current (only if the person has one)
        try:
            result["vault"] = vault.sync(api, settings)
        except Exception as e:                         # the push already succeeded; never fail it over the vault
            result["vault"] = f"not updated: {e}"
    return result


@mcp.tool()
def vault_sync() -> dict:
    """Refresh the read-only Obsidian copy of the knowledge base (one markdown file per decision)."""
    return vault.sync(_api(), _settings())


REVIEW_CAPABILITIES = {"mcp": {"servers": [{"server": "host:superchat", "tools": ["review_list", "push_review"]}]}}


@mcp.tool()
def review_screen() -> dict:
    """
    The visual review screen (Claude desktop app only). Publish `html` with the Artifact tool exactly as given, passing
    `capabilities` unchanged and a title of "Superchat Review". Each person needs their OWN copy: a page can only call a
    local MCP server (host:superchat) for the artifact's owner. Tell them to open it in the Claude desktop app.
    """
    html = resources.files("superchat").joinpath("assets", "review", "template.html").read_text(encoding="utf-8")
    return {"html": html, "capabilities": REVIEW_CAPABILITIES, "title": "Superchat Review",
            "description": "Review and push the decisions you kept.",
            "note": "Without the Artifact tool, or outside the Claude desktop app, review in text instead: review_list then push_review."}


@mcp.tool()
def review_status() -> dict:
    """How many kept decisions are waiting for review on this computer (cheap; used for reminders)."""
    return {"waiting_locally": queue.count(), "last_push": state.get("last_push")}


# ---- command prompts (shown as commands by apps that list MCP prompts) -------------------------------------

@mcp.prompt(name="keep")
def keep_prompt() -> str:
    """Keep every decision from this chat that has not been kept yet."""
    return ("Run /keep: call chat_contributions for this chat, then extract EVERY decision and key note from the whole "
            "chat that is not already kept. Make each distinct item concise and self-contained, with a short title. "
            "Only include condition, reason or original wording when they add necessary information, and never guess. "
            "Call keep and report the counts.")


@mcp.prompt()
def keeponly(what: str) -> str:
    """Keep only the part you describe."""
    return (f"Run /keeponly: keep ONLY this, nothing else from the chat: {what}. Use concise, distinct items. "
            "Omit optional fields unless they add necessary information, then call keep.")


@mcp.prompt()
def superchat(question: str) -> str:
    """Answer using the shared knowledge base, for one company."""
    return (f"Run /superchat: use the knowledge base for ONE company (resolve it; ask if unclear) to answer: {question}. "
            "Label knowledge-base content 'From Superchat DB' and your own reasoning 'Claude's suggestion'.")


@mcp.prompt()
def superchatall(question: str) -> str:
    """Answer using the knowledge base across ALL companies."""
    return (f"Run /superchatall: search ALL companies for: {question}. Label every finding with its company and "
            "keep 'From Superchat DB' separate from 'Claude's suggestion'.")


@mcp.prompt()
def strict() -> str:
    """Stop using the knowledge base for answers in this session."""
    return ("Run /strict: from now on in this session do not use the Superchat knowledge base to answer. "
            "Confirm once. /keep still works.")


@mcp.prompt()
def review() -> str:
    """Review and push everything kept so far."""
    return "Run /review: call review_list, judge duplicates and conflicts, show the list, then do ONE push_review."


def run() -> None:
    paths.home()
    # Native embedding dependencies can hang when first imported in an MCP worker thread on Windows.
    # Import them on the main thread before starting the server; model loading remains lazy.
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pass
    print(f"[superchat] MCP server {__version__} starting", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")
