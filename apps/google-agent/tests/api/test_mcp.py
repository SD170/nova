"""MCP (streamable-HTTP) at /mcp: discovery, calls, auth. Same data as REST."""

import json

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

TOOLS = {"gmail_inbox_summary", "gmail_new_since", "gmail_search", "gmail_get_message",
         "gmail_create_draft", "calendar_list_events", "calendar_free_busy",
         "calendar_create_event", "calendar_sync_canvas", "calendar_auto_sync",
         "research_company", "save_document", "get_workspace_health"}


def rpc(c, method, params=None, headers=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return c.post("/mcp", json=body, headers={**H, **(headers or {})})


def call(c, name, args=None, headers=None):
    r = rpc(c, "tools/call", {"name": name, "arguments": args or {}}, headers)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res, (json.loads(res["content"][0]["text"]) if not res.get("isError") else None)


def test_initialize_and_tools(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.json()["result"]["serverInfo"]["name"] == "workspace"
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOLS and all(t["description"] for t in tools)


def test_inbox_matches_rest(client):
    _, inbox = call(client, "gmail_inbox_summary", {"hours": 72})
    rest = client.get("/gmail/inbox?hours=72").json()
    assert [e["id"] for e in inbox["emails"]] == [e["id"] for e in rest["emails"]]


def test_read_and_draft(client):
    _, msg = call(client, "gmail_get_message", {"message_id": "m-prof"})
    assert "AVL" in msg["body_text"]
    _, d = call(client, "gmail_create_draft", {"body": "Yes, I'll be there.",
                                              "reply_to_message_id": "m-prof"})
    assert d["draft_id"] and "Nothing was sent" in d["note"]


def test_sync_preview_then_apply(client, fake_canvas):
    _, preview = call(client, "calendar_sync_canvas", {})
    assert preview["applied"] is False and preview["counts"]["create"] == 3
    _, done = call(client, "calendar_sync_canvas", {"apply": True})
    assert done["applied"] and done["counts"]["create"] == 3
    _, ev = call(client, "calendar_list_events", {"days_ahead": 10})
    assert sum(e["calendar"] == "nova" for e in ev["events"]) == 3


def test_create_event_and_bad_date(client):
    _, ev = call(client, "calendar_create_event",
                 {"title": "Study: AVL", "start": "2026-11-20T15:00:00-07:00"})
    assert ev["calendar"] == "nova" and ev["end"].startswith("2026-11-20T16:00")
    res, _ = call(client, "calendar_create_event", {"title": "x", "start": "tomorrow-ish"})
    assert res["isError"] and "ISO" in res["content"][0]["text"]


def test_errors_are_tool_errors(client):
    res, _ = call(client, "gmail_get_message", {"message_id": "nope"})
    assert res["isError"] and "No email with id nope" in res["content"][0]["text"]
    res, _ = call(client, "research_company", {"company": "Acme"})
    assert res["isError"] and "TINYFISH_API_KEY" in res["content"][0]["text"]


def test_doc_and_health(client):
    _, d = call(client, "save_document", {"title": "Reply", "content_markdown": "Hi"})
    assert d["format"] == "docx"
    _, h = call(client, "get_workspace_health")
    assert h["ok"] and h["backend"] == "mock"


def test_mcp_requires_key(make_client):
    c = make_client(canvas_api_key="s3cret")
    assert rpc(c, "tools/list").status_code == 401
    assert rpc(c, "tools/list", headers={"X-Canvas-Key": "bad"}).status_code == 401
    assert rpc(c, "tools/list", headers={"X-Jarvis-Key": "s3cret"}).status_code == 401  # old name
    ok = rpc(c, "tools/list", headers={"X-Canvas-Key": "s3cret"})
    assert ok.status_code == 200 and len(ok.json()["result"]["tools"]) == len(TOOLS)
