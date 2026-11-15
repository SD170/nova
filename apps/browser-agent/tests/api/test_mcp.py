"""MCP (streamable-HTTP) at /mcp: discovery, calls, auth. Same data as REST."""

import json

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

TOOLS = {"get_daily_brief", "get_todo_list", "get_item_details", "mark_item_done_locally",
         "unmark_item_done", "list_courses", "get_course_items", "get_course_materials",
         "get_material_text", "sync_canvas", "get_canvas_health"}


def rpc(c, method, params=None, headers=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return c.post("/mcp", json=body, headers={**H, **(headers or {})})


def call(c, name, args=None, headers=None):
    r = rpc(c, "tools/call", {"name": name, "arguments": args or {}}, headers)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res, (json.loads(res["content"][0]["text"]) if not res.get("isError") else None)


def test_initialize(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "canvas"


def test_tools_list(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOLS
    assert all(t["description"] for t in tools)


def test_brief_matches_rest(client):
    _, brief = call(client, "get_daily_brief", {"days": 7})
    rest = client.get("/brief?days=7").json()
    assert [i["id"] for i in brief["items"]] == [i["id"] for i in rest["items"]]


def test_materials_and_text(client):
    _, mats = call(client, "get_course_materials", {"course_id": "cse310", "topic_hint": "heaps"})
    assert [m["id"] for m in mats["materials"]] == ["file-310010"]
    assert "fetch_ref" not in mats["materials"][0]
    _, text = call(client, "get_material_text", {"material_id": "file-310010"})
    assert "[page 2]" in text["text"]


def test_user_done_roundtrip(client):
    _, item = call(client, "mark_item_done_locally", {"item_id": "cse310-a3"})
    assert item["user_done"] is True
    _, item = call(client, "unmark_item_done", {"item_id": "cse310-a3"})
    assert item["in_todo"] is True


def test_errors_are_tool_errors(client):
    res, _ = call(client, "get_item_details", {"item_id": "nope"})
    assert res["isError"]
    res, _ = call(client, "get_material_text", {"material_id": "file-310099"})
    assert res["isError"] and "too_large" in res["content"][0]["text"]


def test_mcp_requires_key(make_client):
    c = make_client(browser_agent_api_key="s3cret")
    assert rpc(c, "tools/list").status_code == 401
    assert rpc(c, "tools/list", headers={"X-Jarvis-Key": "bad"}).status_code == 401
    r = rpc(c, "tools/list", headers={"X-Jarvis-Key": "s3cret"})
    assert r.status_code == 200 and len(r.json()["result"]["tools"]) == len(TOOLS)
