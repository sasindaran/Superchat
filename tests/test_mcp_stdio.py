"""Start the MCP server exactly as Claude does (a subprocess speaking MCP over stdio) and talk to it."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {"login", "verify_code", "whoami", "logout", "chat_tag", "chat_contributions", "keep", "companies",
                  "resolve_context", "link_folder", "match", "brief", "search", "review_list", "push_review", "review_status", "vault_sync", "review_screen"}
EXPECTED_PROMPTS = {"keep", "keeponly", "superchat", "superchatall", "strict", "review"}


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=90))


def params(home):
    return StdioServerParameters(command=sys.executable, args=["-m", "superchat", "mcp"],
                                 env={"SUPERCHAT_HOME": str(home), "SUPERCHAT_SUPABASE_KEY": "", "PATH": ""})


def test_real_stdio_handshake_tools_prompts_and_instructions(tmp_path):
    async def go():
        async with stdio_client(params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                prompts = {p.name for p in (await s.list_prompts()).prompts}
                tag = (await s.call_tool("chat_tag", {})).content[0].text
                who = json.loads((await s.call_tool("whoami", {})).content[0].text)
                status = json.loads((await s.call_tool("review_status", {})).content[0].text)
                return init, tools, prompts, tag, who, status
    init, tools, prompts, tag, who, status = run(go())
    assert init.serverInfo.name == "superchat"
    assert "Capturing" in init.instructions and "/strict" in init.instructions and "From Superchat DB" in init.instructions
    assert tools == EXPECTED_TOOLS
    assert prompts == EXPECTED_PROMPTS
    assert tag.startswith("sc-") and len(tag) == 9
    assert who["signed_in_as"] is None and who["supabase_url"].endswith(".supabase.co")
    assert status["waiting_locally"] == 0


def test_keep_over_the_wire_goes_to_the_local_queue_for_claude_code(tmp_path):
    async def go():
        async with stdio_client(params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("keep", {"chat_id": "wire-1", "items": [
                    {"title": "Wire test", "decision": "Kept through the real protocol", "reason": "token=abcdef123456"}]})
                again = await s.call_tool("keep", {"chat_id": "wire-1", "items": [
                    {"title": "Wire test", "decision": "kept through the REAL protocol"}]})
                return json.loads(res.content[0].text), json.loads(again.content[0].text)
    first, second = run(go())
    assert first["kept"] == 1 and first["stored_in"] == "this computer's queue" and first["waiting_for_review"] == 1
    assert second["kept"] == 0 and second["skipped_as_already_kept"] == ["Wire test"]
    saved = (tmp_path / "queue.jsonl").read_text(encoding="utf-8")
    assert "abcdef123456" not in saved and "REDACTED" in saved


def test_tools_that_need_sign_in_explain_themselves(tmp_path):
    async def go():
        async with stdio_client(params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await s.call_tool("companies", {})
    res = run(go())
    assert res.isError
    assert "publishable key is missing" in res.content[0].text or "Not signed in" in res.content[0].text


def test_review_screen_tool_returns_a_publishable_page(tmp_path):
    async def go():
        async with stdio_client(params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return json.loads((await s.call_tool("review_screen", {})).content[0].text)
    out = run(go())
    assert out["title"] == "Superchat Review"
    assert out["capabilities"] == {"mcp": {"servers": [{"server": "host:superchat", "tools": ["review_list", "push_review"]}]}}
    assert out["html"].lstrip().startswith("<title>Superchat Review</title>") and "host:superchat" in out["html"]
    assert "<!doctype" not in out["html"].lower() and "<body" not in out["html"].lower()    # the skeleton is added on publish
